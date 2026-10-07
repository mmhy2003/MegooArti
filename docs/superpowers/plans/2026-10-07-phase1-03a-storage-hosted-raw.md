# Storage and Hosted Raw Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blob stores, the repository and asset model, a format interface, and hosted Raw repositories reachable at `/repository/{name}/{path}`, so that `curl -T` stores a file of any size and `curl` gets the same bytes back.

**Architecture:** Blobs are files named by their SHA-256 under a blob store directory, written by streaming to a temporary file and renamed into place. A `megooarti.storage` package owns blobs; a `megooarti.repositories` package owns repositories, components and assets. One route sends every repository request through central authentication and authorisation to the repository's format, which works only through a storage facade. Raw is the generic format behaviour unchanged.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, Alembic, pytest + pytest-asyncio + httpx.

**Spec:** [docs/superpowers/specs/2026-10-07-storage-repositories-design.md](../specs/2026-10-07-storage-repositories-design.md), sections marked plan 3a. Business requirements: [docs/BRD.md](../../BRD.md) BLB-1/2/4/6/7, REP-1 to REP-4, CMP-1, FMT-8 (hosted), FMT-23, NFR-2/3/5/11, TSK-5.

## Global Constraints

- Everything in the plan 1 and plan 2 Global Constraints still applies: Alembic only, one migration head, working `downgrade()`, `MEGOOARTI_`-prefixed settings listed in `README.md`, JSON logs, the standard error envelope, services never commit, no ORM relationships, Python-side defaults on columns the code reads back, `megooarti.clock.utcnow()`, LF line endings, 100-character lines, ruff clean, spaced markdown table separators.
- **Asset paths never become file paths.** Files in a blob store are named only by their SHA-256.
- **No database connection is held while a request or response body moves.** Code that is about to receive an upload or stream a download calls `await db.commit()` first, which returns the connection to the pool.
- **All file and hash work runs off the event loop** (`asyncio.to_thread`), in chunks of at most `CHUNK_SIZE`.
- **Only the security package reads `Principal.patterns`.** Everything else calls `authorize(principal, permission)` or `principal.allows(permission)`.
- **Every route authenticates** through `current_principal` or `client_principal`, unless it is on the open list in `tests/test_route_guards.py`.
- Repository content responses always carry `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`.
- A test must never start an application whose `app.state.sessionmaker` commits for real to the shared test database. Tests that need real transactions are synchronous and use the `empty_database` fixture.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker compose` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **An upload that is cut off, or whose size or checksum does not match what the client declared.** Nothing should be stored and no temporary file left (Tasks 3 and 9).
2. **A path that tries to climb out or hide** (`../x`, `a//b`, a backslash, a control character, a trailing slash). It should be `400 invalid_path`, and no file outside the blob store should ever be touched (Task 6).
3. **Two requests writing the same new path at the same moment.** One should create and the other replace; neither should fail with a server error (Task 11).
4. **A range request at the edges** (last byte, suffix longer than the file, start beyond the end, an empty file, several ranges). Each should give the documented result, never a `500` (Task 8).
5. **Deleting the last asset that uses some content while another upload of the same content is being recorded.** The new asset must not end up pointing at a deleted file (Task 11).

---

### Task 1: One place that decides, public repository access, and a default-deny check

**Files:**
- Modify: `backend/src/megooarti/security/authentication.py` (replace the whole file)
- Test: `backend/tests/security/test_authorize.py`
- Test: `backend/tests/test_route_guards.py`

**Interfaces:**
- Consumes: everything `authentication.py` consumed in plan 2; `permissions.is_valid_permission`.
- Produces, in `megooarti.security.authentication`:
  - `Principal` gains `public: frozenset[str]` — what anyone may do on repositories without credentials. `allows(permission)` refuses a malformed permission, grants a `repository:` permission that `public` grants, refuses everything else for an anonymous principal, and otherwise applies patterns and token scopes as before.
  - `unauthorized(message=..., *, scheme="Bearer")` — `scheme` is `"Bearer"` or `"Basic"`.
  - `authorize(principal: Principal | None, permission: str, *, scheme="Bearer") -> Principal` — raises `401`, `403 password_change_required` or `403 forbidden`.
  - `client_principal` — like `current_principal`, but a `401` carries `WWW-Authenticate: Basic realm="MegooArti"`. For repository content routes.
  - `AUTHENTICATION_DEPENDENCIES: frozenset` — `{current_principal, client_principal}`.
  - `require(permission)` and `require_interactive(...)` are unchanged for callers.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_authorize.py`:

```python
import pytest
from fastapi import APIRouter, Depends, FastAPI

from megooarti.errors import ApiError
from megooarti.security import roles, users
from megooarti.security.authentication import Principal, authorize, client_principal, require
from megooarti.security.models import User
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code

MAVEN = "/_test/maven-read"
USERS = "/_test/users-read"
CLIENT = "/_test/client/maven-read"
MAVEN_READ = "repository:maven:releases:read"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    @router.get("/maven-read")
    async def maven_read(principal: Principal = Depends(require(MAVEN_READ))) -> dict:
        return {"user": principal.user.username}

    @router.get("/users-read")
    async def users_read(principal: Principal = Depends(require("admin:users:read"))) -> dict:
        return {"user": principal.user.username}

    @router.get("/client/maven-read")
    async def client_read(principal: Principal | None = Depends(client_principal)) -> dict:
        return {"user": authorize(principal, MAVEN_READ, scheme="Basic").user.username}

    app.include_router(router)
    return app


async def enable_anonymous_access(db) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()


def person(**fields) -> Principal:
    user = User(username="pat", display_name="Pat", must_change_password=False)
    fields.setdefault("method", "password")
    fields.setdefault("patterns", frozenset())
    return Principal(user=user, **fields)


async def test_a_signed_in_user_may_do_what_anyone_may_do(client, make_user, db):
    await make_user("dana")
    headers = basic("dana", PASSWORD)
    assert (await client.get(MAVEN, headers=headers)).status_code == 403

    await enable_anonymous_access(db)

    assert (await client.get(MAVEN, headers=headers)).json() == {"user": "dana"}


async def test_token_scopes_do_not_narrow_public_access(client, make_user, make_token, db):
    dana = await make_user("dana")
    token = await make_token(dana, scopes=["admin:users:read"])
    await enable_anonymous_access(db)

    assert (await client.get(MAVEN, headers=bearer(token))).status_code == 200


async def test_public_access_never_includes_administration(client, make_user, db):
    await roles.create_role(db, "generous", "", ["admin:users:read", "repository"], [])
    anonymous = await users.get_user_by_username(db, "anonymous")
    await users.set_roles(db, anonymous, ["generous"])
    await enable_anonymous_access(db)
    await make_user("dana")

    by_dana = await client.get(USERS, headers=basic("dana", PASSWORD))
    by_nobody = await client.get(USERS)

    assert (by_dana.status_code, error_code(by_dana)) == (403, "forbidden")
    assert by_nobody.status_code == 401


def test_allows_applies_patterns_scopes_and_public_access():
    owner = person(patterns=frozenset({"*"}))
    scoped = person(patterns=frozenset({"*"}), scopes=frozenset({"admin:users:read"}))
    reader = person(public=frozenset({"repository:*:*:read"}))

    assert owner.allows("admin:users:write")
    assert scoped.allows("admin:users:read")
    assert not scoped.allows("admin:users:write")
    assert reader.allows(MAVEN_READ)
    assert not reader.allows("repository:maven:releases:add")
    assert not reader.allows("admin:users:read")


@pytest.mark.parametrize(
    "permission",
    ["repository:maven:a*b:read", "repository:maven::read", "repository:maven:*:read", ""],
)
def test_a_malformed_permission_is_refused_even_with_full_access(permission):
    assert not person(patterns=frozenset({"*"}), public=frozenset({"*"})).allows(permission)


def test_authorize_returns_the_principal_when_allowed():
    owner = person(patterns=frozenset({"*"}))
    assert authorize(owner, "admin:users:read") is owner


@pytest.mark.parametrize(
    ("principal", "status", "code"),
    [
        (None, 401, "unauthorized"),
        (person(), 403, "forbidden"),
        (person(method="anonymous"), 401, "unauthorized"),
    ],
)
def test_authorize_refusals(principal, status, code):
    with pytest.raises(ApiError) as caught:
        authorize(principal, "admin:users:read")
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_authorize_refuses_everything_while_a_password_change_is_pending():
    pending = person(patterns=frozenset({"*"}))
    pending.user.must_change_password = True

    with pytest.raises(ApiError) as caught:
        authorize(pending, "admin:users:read")

    assert caught.value.code == "password_change_required"


@pytest.mark.parametrize("headers", [{}, basic("nobody", "wrong password")])
async def test_client_routes_challenge_with_basic(client, headers):
    response = await client.get(CLIENT, headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_api_routes_still_challenge_with_bearer(client):
    response = await client.get(USERS, headers=basic("nobody", "wrong password"))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="MegooArti"'
```

`backend/tests/test_route_guards.py`:

```python
"""Every route must authenticate unless it is deliberately open."""

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.security.authentication import AUTHENTICATION_DEPENDENCIES

# Routes anyone may call without credentials. Keep this list short and justified.
OPEN = {
    "/api/v1/status/live",  # health checks, required to be unauthenticated (SYS-2)
    "/api/v1/status/ready",
    "/api/v1/auth/login",  # this is where credentials are presented
}


def dependency_calls(dependant) -> set:
    found = set()
    for dependency in dependant.dependencies:
        found.add(dependency.call)
        found |= dependency_calls(dependency)
    return found


def unguarded_routes(app: FastAPI) -> list[str]:
    return sorted(
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path not in OPEN
        and not (dependency_calls(route.dependant) & AUTHENTICATION_DEPENDENCIES)
    )


def test_every_route_authenticates_unless_it_is_on_the_open_list(app):
    assert unguarded_routes(app) == []


def test_the_open_list_names_only_routes_that_exist(app):
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert OPEN <= paths


def test_a_route_that_only_opens_a_database_session_is_reported(app):
    @app.get("/_test/forgot-to-authenticate")
    async def forgot(db: AsyncSession = Depends(get_session)) -> dict:
        return {}

    assert unguarded_routes(app) == ["/_test/forgot-to-authenticate"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_authorize.py tests/test_route_guards.py -q`
Expected: both files fail to collect, with `cannot import name 'authorize'` and `cannot import name 'AUTHENTICATION_DEPENDENCIES'`.

- [ ] **Step 3: Implement**

Replace `backend/src/megooarti/security/authentication.py` with:

```python
"""Who is making this request, and are they allowed to do this?"""

import asyncio
import base64
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.security import sessions, throttle, tokens, users
from megooarti.security.keys import TOKEN_PREFIX
from megooarti.security.models import ApiToken, User, UserSession
from megooarti.security.passwords import hash_password, needs_rehash, verify_password
from megooarti.security.permissions import any_grants, is_valid_permission
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

SESSION_COOKIE = "megooarti_session"
CSRF_HEADER = "X-CSRF-Token"
INVALID_CREDENTIALS = "Invalid credentials."
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

Method = Literal["session", "password", "token", "anonymous"]
Scheme = Literal["Bearer", "Basic"]


@dataclass(frozen=True)
class Principal:
    """The identity a request acts as."""

    user: User
    method: Method
    patterns: frozenset[str]
    scopes: frozenset[str] | None = None
    session: UserSession | None = None
    # What anyone may do without credentials: the anonymous user's patterns while
    # anonymous access is on. Only ever applied to repository permissions.
    public: frozenset[str] = frozenset()

    @property
    def is_anonymous(self) -> bool:
        return self.method == "anonymous"

    @property
    def is_interactive(self) -> bool:
        """Signed in as a person (cookie or password), not with an API token."""
        return self.method in ("session", "password")

    def allows(self, permission: str) -> bool:
        if not is_valid_permission(permission):
            return False  # fail closed on anything that could shift segments
        if permission.startswith("repository:") and any_grants(self.public, permission):
            return True  # public content is public to everyone, whatever a token's scopes
        if self.is_anonymous:
            return False  # whatever roles anonymous holds, nobody administers anonymously
        if not any_grants(self.patterns, permission):
            return False
        return self.scopes is None or any_grants(self.scopes, permission)


def unauthorized(
    message: str = "Authentication is required.", *, scheme: Scheme = "Bearer"
) -> ApiError:
    challenge = {"WWW-Authenticate": f'{scheme} realm="MegooArti"'}
    return ApiError(401, "unauthorized", message, headers=challenge)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _anonymous_access(db: AsyncSession) -> tuple[User, frozenset[str]] | None:
    """The anonymous user and its patterns while anonymous access is on, else None."""
    if not (await get_setting(db, "anonymous_access"))["enabled"]:
        return None
    anonymous = await users.get_user_by_username(db, "anonymous")
    if anonymous is None or anonymous.status != "active":
        return None
    return anonymous, await users.user_patterns(db, anonymous)


async def build_principal(
    db: AsyncSession,
    user: User,
    method: Method,
    *,
    token: ApiToken | None = None,
    session: UserSession | None = None,
) -> Principal:
    """The principal for an identified user."""
    anonymous = await _anonymous_access(db)
    public = frozenset() if anonymous is None else anonymous[1]
    scopes = None if token is None or token.scopes is None else frozenset(token.scopes)
    return Principal(user, method, await users.user_patterns(db, user), scopes, session, public)


async def _checked[T](
    db: AsyncSession,
    request: Request,
    username: str | None,
    attempt: Callable[[], Awaitable[T | None]],
) -> T:
    """Run one credential check under the failed-sign-in limits."""
    settings = request.app.state.settings
    now = utcnow()
    subjects = throttle.subjects(username, client_ip(request))
    standing = await throttle.standing(
        db,
        subjects,
        now=now,
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_failure_window_seconds,
    )
    if standing.blocked_for:
        log.warning("login_throttled", username=username, ip=client_ip(request))
        raise ApiError(
            429,
            "too_many_attempts",
            "Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(standing.blocked_for)},
        )

    result = await attempt()
    if result is None:
        await throttle.record_failure(
            db, subjects, now=now, window_seconds=settings.login_failure_window_seconds
        )
        await db.commit()  # the count must outlive this failed request
        log.info("login_failed", username=username, ip=client_ip(request))
        raise unauthorized(INVALID_CREDENTIALS)
    if standing.has_failures:
        await throttle.clear(db, subjects)
    return result


async def _no_match() -> None:
    """A credential check that has already failed."""
    return None


async def authenticate_password(
    db: AsyncSession, request: Request, username: str, password: str
) -> User:
    """The active user with this username and password, or a 401 / 429 error."""
    username = users.normalise_username(username)
    if "\x00" in username:
        # PostgreSQL cannot store or compare this character, so it is never an account.
        return await _checked(db, request, None, _no_match)

    async def attempt() -> User | None:
        user = await users.get_user_by_username(db, username)
        stored = None if user is None else user.password_hash
        matched = await asyncio.to_thread(verify_password, stored, password)
        if user is None or not matched or user.status != "active":
            return None
        if needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)
        return user

    return await _checked(db, request, username, attempt)


async def _authenticate_token(
    db: AsyncSession, request: Request, value: str, username: str | None = None
) -> tuple[User, ApiToken]:
    async def attempt() -> tuple[User, ApiToken] | None:
        now = utcnow()
        token = await tokens.find_token(db, value, now)
        if token is None:
            return None
        user = await users.get_user(db, token.user_id)
        if user is None or user.status != "active":
            return None
        if username is not None and user.username != users.normalise_username(username):
            return None
        tokens.touch(token, now)
        return user, token

    # A valid token is accepted even from a blocked address. These secrets carry 256 bits
    # of randomness, so limiting guesses protects nothing, while refusing valid ones
    # would let anyone at a shared address stop every pipeline behind it.
    found = await attempt()
    if found is not None:
        return found
    # Count the failure against the address (never a username) and raise 401 or 429.
    return await _checked(db, request, None, _no_match)


def _decode_basic(credentials: str) -> tuple[str, str]:
    try:
        decoded = base64.b64decode(credentials.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise unauthorized("The Authorization header is malformed.") from None
    username, separator, secret = decoded.partition(":")
    if not separator:
        raise unauthorized("The Authorization header is malformed.")
    return username, secret


async def _from_header(db: AsyncSession, request: Request, header: str) -> Principal:
    scheme, _, credentials = header.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer":
        user, token = await _authenticate_token(db, request, credentials.strip())
        return await build_principal(db, user, "token", token=token)
    if scheme == "basic":
        username, secret = _decode_basic(credentials)
        if secret.startswith(TOKEN_PREFIX):
            user, token = await _authenticate_token(db, request, secret, username)
            return await build_principal(db, user, "token", token=token)
        user = await authenticate_password(db, request, username, secret)
        return await build_principal(db, user, "password")
    raise unauthorized("The Authorization scheme is not supported.")


async def resolve_principal(request: Request, db: AsyncSession) -> Principal | None:
    """The principal for this request, or None when there are no credentials.

    Invalid credentials in an Authorization header are an error, never a fall-through
    to the cookie or to anonymous access.
    """
    header = request.headers.get("Authorization")
    if header:
        return await _from_header(db, request, header)

    settings = request.app.state.settings
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        now = utcnow()
        record = await sessions.find_session(
            db, cookie, now=now, idle_seconds=settings.session_idle_seconds
        )
        if record is not None:
            user = await users.get_user(db, record.user_id)
            if user is not None and user.status == "active":
                sessions.touch(record, now)
                return await build_principal(db, user, "session", session=record)

    anonymous = await _anonymous_access(db)
    if anonymous is not None:
        user, patterns = anonymous
        return Principal(user, "anonymous", patterns, public=patterns)
    return None


def _principal_dependency(scheme: Scheme) -> Callable[..., Awaitable[Principal | None]]:
    async def dependency(
        request: Request, db: AsyncSession = Depends(get_session)
    ) -> Principal | None:
        try:
            principal = await resolve_principal(request, db)
        except ApiError as error:
            if error.status_code != 401:
                raise
            raise unauthorized(error.message, scheme=scheme) from None
        await db.commit()  # last-seen times, cleared failure counts, upgraded password hashes
        if (
            principal is not None
            and principal.session is not None
            and request.method in _UNSAFE_METHODS
        ):
            sent = request.headers.get(CSRF_HEADER, "")
            expected = principal.session.csrf_token
            if not secrets.compare_digest(sent.encode(), expected.encode()):
                raise ApiError(403, "csrf_failed", "The CSRF token is missing or wrong.")
        return principal

    return dependency


# Who is calling, if anyone. Both enforce CSRF for cookie requests; they differ only in
# the challenge a 401 carries.
current_principal = _principal_dependency("Bearer")  # the JSON API
client_principal = _principal_dependency("Basic")  # repository content, for package clients
AUTHENTICATION_DEPENDENCIES = frozenset({current_principal, client_principal})


def _refuse_pending_password_change(principal: Principal) -> None:
    if principal.is_interactive and principal.user.must_change_password:
        raise ApiError(
            403, "password_change_required", "Change your password before doing anything else."
        )


def authorize(
    principal: Principal | None, permission: str, *, scheme: Scheme = "Bearer"
) -> Principal:
    """The one place that decides whether a caller may do something."""
    if principal is None:
        raise unauthorized(scheme=scheme)
    _refuse_pending_password_change(principal)
    if not principal.allows(permission):
        if principal.is_anonymous:
            raise unauthorized(scheme=scheme)
        raise ApiError(403, "forbidden", "You do not have permission to do this.")
    return principal


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must hold `permission`."""

    async def dependency(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        return authorize(principal, permission)

    return dependency


def require_interactive(
    *, allow_pending_password_change: bool = False
) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must be signed in as a person, not with a token."""

    async def dependency(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        if principal is None or principal.is_anonymous:
            raise unauthorized()
        if not principal.is_interactive:
            raise ApiError(
                403,
                "interactive_auth_required",
                "Sign in with your password to do this; an API token is not enough.",
            )
        if not allow_pending_password_change:
            _refuse_pending_password_change(principal)
        return principal

    return dependency
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_authorize.py tests/test_route_guards.py -q`
Expected: 19 passed.

Run in `backend/`: `uv run pytest -q`
Expected: no failures. The plan 2 tests are unchanged and prove that behaviour for existing callers is the same.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(security): add authorize, public repository access and a default-deny route check"
```

---

### Task 2: Settings, tables and the default blob store

**Files:**
- Modify: `backend/src/megooarti/config.py`
- Create: `backend/src/megooarti/storage/__init__.py` (empty)
- Create: `backend/src/megooarti/storage/models.py`
- Create: `backend/src/megooarti/repositories/__init__.py` (empty)
- Create: `backend/src/megooarti/repositories/models.py`
- Modify: `backend/src/megooarti/models.py`
- Create: `backend/src/megooarti/migrations/versions/0003_add_storage_and_repositories.py`
- Modify: `backend/tests/test_config.py`
- Test: `backend/tests/storage/__init__.py` (empty), `backend/tests/storage/test_models.py`

**Interfaces:**
- Consumes: `Base`, `utcnow`.
- Produces:
  - `Settings.compaction_interval_seconds: int = 3600`, `Settings.blob_grace_seconds: int = 86400`
  - `megooarti.storage.models`: `BlobStore(id, name, type, config, created_at)`; `Blob(id, blob_store_id, sha256, md5, sha1, sha512, size, created_at, unreferenced_since)`
  - `megooarti.repositories.models`: `Repository(id, name, name_key, format, type, online, blob_store_id, config, created_at, updated_at)`; `Component(id, repository_id, namespace, name, version, attributes, created_at, updated_at)`; `Asset(id, repository_id, component_id, path, blob_id, content_type, kind, attributes, created_by, created_at, updated_at, last_downloaded_at, last_verified_at)`
  - `Asset.updated_at` has no automatic update: set it when the content changes, so that noting a download does not change `Last-Modified`.
  - A blob store row named `default`, type `file`, config `{"path": "default"}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/storage/__init__.py` as an empty file.

`backend/tests/storage/test_models.py`:

```python
from sqlalchemy import select

from megooarti.repositories.models import Asset, Component, Repository
from megooarti.storage.models import Blob, BlobStore


async def test_the_default_blob_store_exists(db):
    store = await db.scalar(select(BlobStore).where(BlobStore.name == "default"))

    assert (store.type, store.config) == ("file", {"path": "default"})


async def test_a_repository_with_a_component_an_asset_and_a_blob(db):
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id, sha256="a" * 64, md5="b" * 32, sha1="c" * 40, sha512="d" * 128, size=3
    )
    repository = Repository(
        name="Files", name_key="files", format="raw", type="hosted", blob_store_id=store.id
    )
    db.add_all([blob, repository])
    await db.flush()
    component = Component(repository_id=repository.id, namespace="docs", name="a.txt")
    db.add(component)
    await db.flush()
    asset = Asset(
        repository_id=repository.id,
        component_id=component.id,
        path="docs/a.txt",
        blob_id=blob.id,
        content_type="text/plain",
        created_by="dana",
    )
    db.add(asset)
    await db.flush()

    assert (repository.online, repository.config) == (True, {})
    assert (component.version, component.attributes) == ("", {})
    assert (asset.kind, asset.attributes) == ("asset", {})
    assert asset.created_at is not None
    assert asset.updated_at is not None
    assert (asset.last_downloaded_at, asset.last_verified_at) == (None, None)
    assert (blob.created_at is not None, blob.unreferenced_since) == (True, None)


async def test_noting_a_download_does_not_change_when_the_asset_was_updated(db):
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id, sha256="e" * 64, md5="b" * 32, sha1="c" * 40, sha512="d" * 128, size=1
    )
    repository = Repository(
        name="files", name_key="files", format="raw", type="hosted", blob_store_id=store.id
    )
    db.add_all([blob, repository])
    await db.flush()
    asset = Asset(
        repository_id=repository.id,
        path="a.txt",
        blob_id=blob.id,
        content_type="text/plain",
        created_by="dana",
    )
    db.add(asset)
    await db.flush()
    updated = asset.updated_at

    asset.last_downloaded_at = asset.created_at
    await db.flush()

    assert asset.updated_at == updated
```

Append to `backend/tests/test_config.py`:

```python


def test_storage_defaults():
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert settings.compaction_interval_seconds == 3600
    assert settings.blob_grace_seconds == 86400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/storage/test_models.py tests/test_config.py -q`
Expected: `test_models.py` fails to collect with `No module named 'megooarti.repositories'`; `test_storage_defaults` fails with `AttributeError`.

- [ ] **Step 3: Add the settings and the models**

In `backend/src/megooarti/config.py`, add to `Settings` after `login_failure_window_seconds`:

```python
    compaction_interval_seconds: int = 3600
    blob_grace_seconds: int = 86400
```

Create `backend/src/megooarti/storage/__init__.py` and `backend/src/megooarti/repositories/__init__.py` as empty files.

`backend/src/megooarti/storage/models.py`:

```python
"""Blob stores and the blobs in them."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class BlobStore(Base):
    __tablename__ = "blob_stores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Blob(Base):
    """One piece of content in one blob store, named by its SHA-256."""

    __tablename__ = "blobs"
    __table_args__ = (UniqueConstraint("blob_store_id", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    blob_store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blob_stores.id", ondelete="RESTRICT")
    )
    sha256: Mapped[str] = mapped_column(String(64))
    md5: Mapped[str] = mapped_column(String(32))
    sha1: Mapped[str] = mapped_column(String(40))
    sha512: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # A hint for compaction: when the last asset using this blob went away.
    unreferenced_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`backend/src/megooarti/repositories/models.py`:

```python
"""Repositories and what they hold: components (packages) made of assets (files)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # The name in lower case: names are unique ignoring case, but looked up exactly.
    name_key: Mapped[str] = mapped_column(String(64), unique=True)
    format: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(16))
    online: Mapped[bool] = mapped_column(default=True)
    blob_store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("blob_stores.id", ondelete="RESTRICT")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("repository_id", "namespace", "name", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    namespace: Mapped[str] = mapped_column(String(1024), default="")
    name: Mapped[str] = mapped_column(String(1024))
    version: Mapped[str] = mapped_column(String(255), default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1024))
    blob_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blobs.id", ondelete="RESTRICT"), index=True
    )
    content_type: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="asset")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set by the code when the content changes. Deliberately no onupdate: noting a
    # download must not change Last-Modified.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

In `backend/src/megooarti/models.py`, add below the existing imports:

```python
from megooarti.repositories import models as _repository_models  # noqa: F401
from megooarti.storage import models as _storage_models  # noqa: F401
```

- [ ] **Step 4: Write the migration**

`backend/src/megooarti/migrations/versions/0003_add_storage_and_repositories.py`:

```python
"""add storage and repositories

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    blob_stores = op.create_table(
        "blob_stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("config", _json(), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blob_stores")),
        sa.UniqueConstraint("name", name=op.f("uq_blob_stores_name")),
    )
    op.create_table(
        "blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("blob_store_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("md5", sa.String(length=32), nullable=False),
        sa.Column("sha1", sa.String(length=40), nullable=False),
        sa.Column("sha512", sa.String(length=128), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        _timestamp("created_at"),
        _timestamp("unreferenced_since", nullable=True),
        sa.ForeignKeyConstraint(
            ["blob_store_id"],
            ["blob_stores.id"],
            name=op.f("fk_blobs_blob_store_id_blob_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blobs")),
        sa.UniqueConstraint("blob_store_id", "sha256", name=op.f("uq_blobs_blob_store_id")),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("blob_store_id", sa.Uuid(), nullable=True),
        sa.Column("config", _json(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["blob_store_id"],
            ["blob_stores.id"],
            name=op.f("fk_repositories_blob_store_id_blob_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint("name", name=op.f("uq_repositories_name")),
        sa.UniqueConstraint("name_key", name=op.f("uq_repositories_name_key")),
    )
    op.create_table(
        "components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("attributes", _json(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_components_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_components")),
        sa.UniqueConstraint(
            "repository_id",
            "namespace",
            "name",
            "version",
            name=op.f("uq_components_repository_id"),
        ),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("blob_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("attributes", _json(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("last_downloaded_at", nullable=True),
        _timestamp("last_verified_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_assets_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["components.id"],
            name=op.f("fk_assets_component_id_components"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blob_id"], ["blobs.id"], name=op.f("fk_assets_blob_id_blobs"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("repository_id", "path", name=op.f("uq_assets_repository_id")),
    )
    op.create_index(op.f("ix_assets_component_id"), "assets", ["component_id"], unique=False)
    op.create_index(op.f("ix_assets_blob_id"), "assets", ["blob_id"], unique=False)

    op.bulk_insert(
        blob_stores,
        [
            {
                "id": uuid.uuid4(),
                "name": "default",
                "type": "file",
                "config": {"path": "default"},
                "created_at": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assets_blob_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_component_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_table("components")
    op.drop_table("repositories")
    op.drop_table("blobs")
    op.drop_table("blob_stores")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/storage/test_models.py tests/test_config.py tests/test_migrations.py tests/test_db_script.py -q`
Expected: no failures. `test_models_and_migrations_describe_the_same_schema` proves the migration matches the models; if it fails, its message lists what to correct in the migration.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(storage): add blob store, blob, repository, component and asset tables"
```

---

### Task 3: The filesystem blob backend

**Files:**
- Create: `backend/src/megooarti/storage/backends.py`
- Test: `backend/tests/storage/test_backends.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `megooarti.storage.backends`:
  - `CHUNK_SIZE = 1024 * 1024`
  - `StagedBlob(token: str, sha256: str, md5: str, sha1: str, sha512: str, size: int)` (frozen dataclass)
  - `BlobBackend` (Protocol) with:
    - `async stage(chunks: AsyncIterator[bytes]) -> StagedBlob` — writes to temporary storage while hashing; leaves nothing behind if the iterator raises
    - `async commit(staged) -> None` — makes the content permanent under its SHA-256; a no-op for content already there; consumes the staged data
    - `async discard(staged) -> None` — removes staged data; safe to call after `commit`
    - `open(sha256, start=0, end=None) -> AsyncIterator[bytes]` — `end` is inclusive
    - `async exists(sha256) -> bool`
    - `async delete(sha256) -> None` — no error if absent
    - `async available_bytes() -> int | None`
    - `async sweep_temporary(older_than_seconds: float) -> int`
  - `FileBlobBackend(root: Path)` implementing it, with files at `<root>/content/<aa>/<bb>/<sha256>` and `<root>/tmp/<random>`

- [ ] **Step 1: Write the failing tests**

`backend/tests/storage/test_backends.py`:

```python
import hashlib
import os
import time
from collections.abc import AsyncIterator

import pytest

from megooarti.storage import backends
from megooarti.storage.backends import FileBlobBackend

BODY = bytes(range(256)) * 41  # 10,496 bytes: not a multiple of the test chunk size


async def pieces(body: bytes, size: int = 700) -> AsyncIterator[bytes]:
    for start in range(0, len(body), size):
        yield body[start : start + size]


async def read(backend: FileBlobBackend, sha256: str, start: int = 0, end: int | None = None) -> bytes:
    return b"".join([chunk async for chunk in backend.open(sha256, start, end)])


def temporary_files(root) -> list:
    directory = root / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


@pytest.fixture
def backend(tmp_path, monkeypatch) -> FileBlobBackend:
    monkeypatch.setattr(backends, "CHUNK_SIZE", 1024)
    return FileBlobBackend(tmp_path / "store")


async def test_stage_reports_size_and_every_checksum(backend):
    staged = await backend.stage(pieces(BODY))

    assert staged.size == len(BODY)
    assert staged.sha256 == hashlib.sha256(BODY).hexdigest()
    assert staged.md5 == hashlib.md5(BODY).hexdigest()
    assert staged.sha1 == hashlib.sha1(BODY).hexdigest()
    assert staged.sha512 == hashlib.sha512(BODY).hexdigest()


async def test_committed_content_is_stored_under_its_hash_and_read_back(backend, tmp_path):
    staged = await backend.stage(pieces(BODY))
    assert not await backend.exists(staged.sha256)

    await backend.commit(staged)

    sha = staged.sha256
    assert (tmp_path / "store" / "content" / sha[:2] / sha[2:4] / sha).is_file()
    assert await backend.exists(sha)
    assert await read(backend, sha) == BODY
    assert temporary_files(tmp_path / "store") == []


async def test_an_empty_body_can_be_stored(backend):
    staged = await backend.stage(pieces(b""))
    await backend.commit(staged)

    assert staged.size == 0
    assert await read(backend, staged.sha256) == b""


async def test_committing_the_same_content_twice_keeps_one_file(backend, tmp_path):
    first = await backend.stage(pieces(BODY))
    await backend.commit(first)
    second = await backend.stage(pieces(BODY))
    await backend.commit(second)

    stored = [path for path in (tmp_path / "store" / "content").rglob("*") if path.is_file()]
    assert len(stored) == 1
    assert temporary_files(tmp_path / "store") == []


async def test_content_moves_in_bounded_chunks(backend, monkeypatch):
    written = []
    real_write = backends._write

    def spy(handle, hashers, data):
        written.append(len(data))
        real_write(handle, hashers, data)

    monkeypatch.setattr(backends, "_write", spy)

    staged = await backend.stage(pieces(BODY, size=5000))
    await backend.commit(staged)
    read_sizes = [len(chunk) async for chunk in backend.open(staged.sha256)]

    assert sum(written) == len(BODY)
    assert max(written) <= 1024
    assert len(written) > 5
    assert max(read_sizes) <= 1024


async def test_an_interrupted_stream_leaves_nothing_behind(backend, tmp_path):
    async def broken() -> AsyncIterator[bytes]:
        yield BODY[:3000]
        raise ConnectionError("the client went away")

    with pytest.raises(ConnectionError):
        await backend.stage(broken())

    assert temporary_files(tmp_path / "store") == []


async def test_discard_removes_staged_content_and_is_safe_after_commit(backend, tmp_path):
    staged = await backend.stage(pieces(BODY))
    await backend.discard(staged)
    assert temporary_files(tmp_path / "store") == []

    kept = await backend.stage(pieces(BODY))
    await backend.commit(kept)
    await backend.discard(kept)

    assert await backend.exists(kept.sha256)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0, 0, BODY[:1]),
        (10, 2999, BODY[10:3000]),
        (len(BODY) - 1, len(BODY) - 1, BODY[-1:]),
        (5000, None, BODY[5000:]),
    ],
)
async def test_open_reads_an_inclusive_range(backend, start, end, expected):
    staged = await backend.stage(pieces(BODY))
    await backend.commit(staged)

    assert await read(backend, staged.sha256, start, end) == expected


async def test_delete_removes_content_and_ignores_what_is_absent(backend):
    staged = await backend.stage(pieces(BODY))
    await backend.commit(staged)

    await backend.delete(staged.sha256)
    await backend.delete(staged.sha256)

    assert not await backend.exists(staged.sha256)


async def test_available_bytes_works_before_the_store_directory_exists(backend):
    assert await backend.available_bytes() > 0


async def test_sweep_removes_only_old_temporary_files(backend, tmp_path):
    old = await backend.stage(pieces(BODY))
    fresh = await backend.stage(pieces(BODY))
    two_days_ago = time.time() - 2 * 86400
    os.utime(old.token, (two_days_ago, two_days_ago))

    removed = await backend.sweep_temporary(older_than_seconds=86400)

    assert removed == 1
    assert [str(path) for path in temporary_files(tmp_path / "store")] == [fresh.token]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/storage/test_backends.py -q`
Expected: collection error, `cannot import name 'backends' from 'megooarti.storage'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/storage/backends.py`:

```python
"""Where blob bytes live. One backend today: a directory on a filesystem.

Content is named only by its SHA-256, so nothing a client sends can choose a file path.
All file and hash work runs in worker threads, in chunks of at most CHUNK_SIZE.
"""

import asyncio
import hashlib
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

CHUNK_SIZE = 1024 * 1024
_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


@dataclass(frozen=True)
class StagedBlob:
    """Content received and hashed, but not yet permanent."""

    token: str  # where the backend is holding it; meaningful only to that backend
    sha256: str
    md5: str
    sha1: str
    sha512: str
    size: int


class BlobBackend(Protocol):
    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob: ...

    async def commit(self, staged: StagedBlob) -> None: ...

    async def discard(self, staged: StagedBlob) -> None: ...

    def open(self, sha256: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]: ...

    async def exists(self, sha256: str) -> bool: ...

    async def delete(self, sha256: str) -> None: ...

    async def available_bytes(self) -> int | None: ...

    async def sweep_temporary(self, older_than_seconds: float) -> int: ...


def _write(handle: BinaryIO, hashers: dict, data: bytes) -> None:
    handle.write(data)
    for hasher in hashers.values():
        hasher.update(data)


def _finish(handle: BinaryIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


class FileBlobBackend:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _content_path(self, sha256: str) -> Path:
        return self._root / "content" / sha256[:2] / sha256[2:4] / sha256

    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob:
        directory = self._root / "tmp"
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        temporary = directory / uuid.uuid4().hex
        # MD5 and SHA-1 are published for clients that expect them, not used for security.
        hashers = {name: hashlib.new(name, usedforsecurity=False) for name in _ALGORITHMS}
        size = 0
        pending = bytearray()
        handle = await asyncio.to_thread(open, temporary, "wb")
        try:
            async for chunk in chunks:
                pending += chunk
                size += len(chunk)
                while len(pending) >= CHUNK_SIZE:
                    piece = bytes(pending[:CHUNK_SIZE])
                    del pending[:CHUNK_SIZE]
                    await asyncio.to_thread(_write, handle, hashers, piece)
            if pending:
                await asyncio.to_thread(_write, handle, hashers, bytes(pending))
            await asyncio.to_thread(_finish, handle)
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
        digests = {name: hasher.hexdigest() for name, hasher in hashers.items()}
        return StagedBlob(token=str(temporary), size=size, **digests)

    async def commit(self, staged: StagedBlob) -> None:
        def place() -> None:
            temporary = Path(staged.token)
            final = self._content_path(staged.sha256)
            if final.exists():
                temporary.unlink(missing_ok=True)
                return
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, final)

        await asyncio.to_thread(place)

    async def discard(self, staged: StagedBlob) -> None:
        await asyncio.to_thread(Path(staged.token).unlink, True)

    async def open(self, sha256: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        handle = await asyncio.to_thread(open, self._content_path(sha256), "rb")
        try:
            if start:
                await asyncio.to_thread(handle.seek, start)
            remaining = None if end is None else end - start + 1
            while remaining is None or remaining > 0:
                wanted = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
                chunk = await asyncio.to_thread(handle.read, wanted)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk
        finally:
            handle.close()

    async def exists(self, sha256: str) -> bool:
        return await asyncio.to_thread(self._content_path(sha256).is_file)

    async def delete(self, sha256: str) -> None:
        await asyncio.to_thread(self._content_path(sha256).unlink, True)

    async def available_bytes(self) -> int | None:
        def free() -> int:
            existing = self._root
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            return shutil.disk_usage(existing).free

        return await asyncio.to_thread(free)

    async def sweep_temporary(self, older_than_seconds: float) -> int:
        def sweep() -> int:
            directory = self._root / "tmp"
            if not directory.exists():
                return 0
            cutoff = time.time() - older_than_seconds
            removed = 0
            for path in directory.iterdir():
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            return removed

        return await asyncio.to_thread(sweep)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/storage/test_backends.py -q`
Expected: 14 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(storage): add the filesystem blob backend"
```

---

### Task 4: Blob stores and blob records

**Files:**
- Create: `backend/src/megooarti/storage/blob_stores.py`
- Create: `backend/src/megooarti/storage/blobs.py`
- Create: `backend/tests/storage/conftest.py`
- Test: `backend/tests/storage/test_blob_stores.py`
- Test: `backend/tests/storage/test_blobs.py`

**Interfaces:**
- Consumes: models (Task 2), `FileBlobBackend`, `StagedBlob` (Task 3), `ApiError`, `Settings.data_dir`.
- Produces, in `megooarti.storage.blob_stores`:
  - `BlobStoreView(name, type, path, blob_count, total_bytes, available_bytes)` (frozen dataclass)
  - `root_of(settings, store) -> Path` — a relative `config["path"]` is under `<data_dir>/blobs/`
  - `backend_for(settings, store) -> BlobBackend`
  - `get_blob_store(db, name) -> BlobStore | None`
  - `describe(db, settings, store) -> BlobStoreView`
  - `list_blob_stores(db, settings, limit, offset) -> tuple[list[BlobStoreView], int]`
  - `create_blob_store(db, *, name, type, path) -> BlobStore` — `409 conflict`, `422 validation_error`
  - `delete_blob_store(db, store) -> None` — `409 in_use` while a repository uses it
- Produces, in `megooarti.storage.blobs`:
  - `lock_blob(db, sha256) -> None` — transaction-level advisory lock for that content
  - `record(db, backend, blob_store_id, staged) -> Blob` — takes the lock, makes the staged content permanent, and returns the blob row with `unreferenced_since` cleared. Call it inside the transaction that will reference the blob.
  - `dereference(db, blob_ids, now) -> None` — marks as unreferenced those blobs that no asset uses any more
  - `referenced` — a SQL expression: "some asset uses this blob"
- Test fixtures (in `tests/storage/conftest.py`): `default_store` (the `BlobStore` row), `backend` (its backend under the test's temporary data directory), `stage(body: bytes) -> StagedBlob`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/storage/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from megooarti.storage.backends import StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore


@pytest.fixture
async def default_store(db) -> BlobStore:
    return await db.scalar(select(BlobStore).where(BlobStore.name == "default"))


@pytest.fixture
def backend(settings, default_store):
    return backend_for(settings, default_store)


@pytest.fixture
def stage(backend):
    async def stage_bytes(body: bytes) -> StagedBlob:
        async def chunks() -> AsyncIterator[bytes]:
            yield body

        return await backend.stage(chunks())

    return stage_bytes
```

`backend/tests/storage/test_blob_stores.py`:

```python
import pytest

from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.storage import blob_stores, blobs


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def test_the_default_store_lives_under_the_data_directory(settings, default_store):
    assert blob_stores.root_of(settings, default_store) == settings.data_dir / "blobs" / "default"


async def test_describe_reports_usage(db, settings, default_store, backend, stage):
    await blobs.record(db, backend, default_store.id, await stage(b"12345"))
    await blobs.record(db, backend, default_store.id, await stage(b"1234567"))

    view = await blob_stores.describe(db, settings, default_store)

    assert (view.name, view.type, view.path) == ("default", "file", "default")
    assert (view.blob_count, view.total_bytes) == (2, 12)
    assert view.available_bytes > 0


async def test_create_defaults_the_path_to_the_name(db, settings):
    store = await blob_stores.create_blob_store(db, name="archive", type="file", path=None)

    assert store.config == {"path": "archive"}
    assert blob_stores.root_of(settings, store) == settings.data_dir / "blobs" / "archive"
    assert (await blob_stores.get_blob_store(db, "archive")).id == store.id


async def test_an_absolute_path_is_used_as_given(db, settings, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    store = await blob_stores.create_blob_store(
        db, name="big-disk", type="file", path=str(elsewhere)
    )

    assert blob_stores.root_of(settings, store) == elsewhere


async def test_a_duplicate_name_is_a_conflict(db):
    error = await error_of(blob_stores.create_blob_store(db, name="default", type="file", path=None))
    assert (error.status_code, error.code) == (409, "conflict")


@pytest.mark.parametrize(
    ("type", "path"), [("s3", None), ("file", "../outside"), ("file", "a/../../b"), ("file", "")]
)
async def test_invalid_stores_are_rejected(db, type, path):
    error = await error_of(blob_stores.create_blob_store(db, name="new", type=type, path=path))
    assert (error.status_code, error.code) == (422, "validation_error")


async def test_list_is_paged_in_name_order(db, settings):
    await blob_stores.create_blob_store(db, name="archive", type="file", path=None)

    page, total = await blob_stores.list_blob_stores(db, settings, limit=1, offset=1)

    assert total == 2
    assert [view.name for view in page] == ["default"]


async def test_a_store_in_use_cannot_be_deleted(db, default_store):
    db.add(
        Repository(
            name="files",
            name_key="files",
            format="raw",
            type="hosted",
            blob_store_id=default_store.id,
        )
    )
    await db.flush()

    error = await error_of(blob_stores.delete_blob_store(db, default_store))

    assert (error.status_code, error.code) == (409, "in_use")


async def test_an_unused_store_is_deleted_with_its_blob_records(db, settings, stage):
    store = await blob_stores.create_blob_store(db, name="archive", type="file", path=None)
    await blobs.record(
        db, blob_stores.backend_for(settings, store), store.id, await stage(b"left behind")
    )

    await blob_stores.delete_blob_store(db, store)

    assert await blob_stores.get_blob_store(db, "archive") is None
```

`backend/tests/storage/test_blobs.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Repository
from megooarti.storage import blobs
from megooarti.storage.models import Blob

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def add_asset(db, store, blob: Blob, path: str) -> Asset:
    repository = await db.scalar(select(Repository).where(Repository.name == "files"))
    if repository is None:
        repository = Repository(
            name="files", name_key="files", format="raw", type="hosted", blob_store_id=store.id
        )
        db.add(repository)
        await db.flush()
    asset = Asset(
        repository_id=repository.id,
        path=path,
        blob_id=blob.id,
        content_type="application/octet-stream",
        created_by="dana",
    )
    db.add(asset)
    await db.flush()
    return asset


async def test_record_makes_content_permanent_and_describes_it(db, default_store, backend, stage):
    staged = await stage(b"hello")

    blob = await blobs.record(db, backend, default_store.id, staged)

    assert await backend.exists(staged.sha256)
    assert (blob.sha256, blob.md5, blob.sha1, blob.sha512, blob.size) == (
        staged.sha256,
        staged.md5,
        staged.sha1,
        staged.sha512,
        5,
    )
    assert blob.unreferenced_since is None


async def test_recording_the_same_content_twice_gives_one_blob(db, default_store, backend, stage):
    first = await blobs.record(db, backend, default_store.id, await stage(b"same"))
    second = await blobs.record(db, backend, default_store.id, await stage(b"same"))

    assert second.id == first.id
    assert await db.scalar(select(func.count()).select_from(Blob)) == 1


async def test_recording_content_again_clears_the_unreferenced_mark(
    db, default_store, backend, stage
):
    blob = await blobs.record(db, backend, default_store.id, await stage(b"again"))
    blob.unreferenced_since = NOW
    await db.flush()

    await blobs.record(db, backend, default_store.id, await stage(b"again"))

    assert blob.unreferenced_since is None


async def test_record_replaces_a_file_that_went_missing(db, default_store, backend, stage):
    blob = await blobs.record(db, backend, default_store.id, await stage(b"fragile"))
    await backend.delete(blob.sha256)

    await blobs.record(db, backend, default_store.id, await stage(b"fragile"))

    assert await backend.exists(blob.sha256)


async def test_dereference_marks_only_blobs_no_asset_uses(db, default_store, backend, stage):
    used = await blobs.record(db, backend, default_store.id, await stage(b"used"))
    unused = await blobs.record(db, backend, default_store.id, await stage(b"unused"))
    await add_asset(db, default_store, used, "a.bin")

    await blobs.dereference(db, [used.id, unused.id], NOW)
    await db.refresh(used)
    await db.refresh(unused)

    assert used.unreferenced_since is None
    assert unused.unreferenced_since == NOW


async def test_dereference_with_nothing_to_do(db):
    await blobs.dereference(db, [], NOW)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/storage/test_blob_stores.py tests/storage/test_blobs.py -q`
Expected: collection error in `tests/storage/conftest.py`, `No module named 'megooarti.storage.blob_stores'`.

- [ ] **Step 3: Implement blob records**

`backend/src/megooarti/storage/blobs.py`:

```python
"""Blob records: which content exists in which store, and whether anything uses it."""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.models import Asset
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.models import Blob

# First key of the two-key advisory lock; the second is derived from the content hash.
_LOCK_NAMESPACE = 0x4D47

# "Some asset uses this blob." For WHERE clauses on Blob.
referenced = exists().where(Asset.blob_id == Blob.id)


def _lock_key(sha256: str) -> int:
    return int.from_bytes(bytes.fromhex(sha256[:8]), "big", signed=True)


async def lock_blob(db: AsyncSession, sha256: str) -> None:
    """Serialise work on one piece of content until this transaction ends.

    Recording an upload and compacting the same content both take this lock, so a blob
    cannot be removed while a new reference to it is being written.
    """
    await db.execute(
        text(f"SELECT pg_advisory_xact_lock({_LOCK_NAMESPACE}, {_lock_key(sha256)})")
    )


async def record(
    db: AsyncSession, backend: BlobBackend, blob_store_id: uuid.UUID, staged: StagedBlob
) -> Blob:
    """Make staged content permanent and return its blob row.

    Call inside the transaction that will reference the blob. The file is put in place
    whenever it is missing, whatever the row says, so a lost file is always repaired.
    """
    await lock_blob(db, staged.sha256)
    await backend.commit(staged)
    blob = await db.scalar(
        select(Blob).where(Blob.blob_store_id == blob_store_id, Blob.sha256 == staged.sha256)
    )
    if blob is None:
        blob = Blob(
            blob_store_id=blob_store_id,
            sha256=staged.sha256,
            md5=staged.md5,
            sha1=staged.sha1,
            sha512=staged.sha512,
            size=staged.size,
        )
        db.add(blob)
    else:
        blob.unreferenced_since = None
    await db.flush()
    return blob


async def dereference(db: AsyncSession, blob_ids: Iterable[uuid.UUID], now: datetime) -> None:
    """Mark as unreferenced those of these blobs that no asset uses any more.

    The mark is a hint. Compaction checks again, under the lock, before removing anything.
    """
    ids = list(set(blob_ids))
    if not ids:
        return
    await db.execute(
        update(Blob).where(Blob.id.in_(ids), ~referenced).values(unreferenced_since=now)
    )
```

`commit` on a file that is already in place only discards the staged copy, and it runs after the lock is taken, so "the file is put in place whenever it is missing" holds: `FileBlobBackend.commit` checks the file itself.

- [ ] **Step 4: Implement blob stores**

`backend/src/megooarti/storage/blob_stores.py`:

```python
"""Blob stores: named places where blob content is kept."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.storage.backends import BlobBackend, FileBlobBackend
from megooarti.storage.models import Blob, BlobStore


@dataclass(frozen=True)
class BlobStoreView:
    name: str
    type: str
    path: str
    blob_count: int
    total_bytes: int
    available_bytes: int | None


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _is_absolute(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def root_of(settings: Settings, store: BlobStore) -> Path:
    path = store.config["path"]
    return Path(path) if _is_absolute(path) else settings.data_dir / "blobs" / path


def backend_for(settings: Settings, store: BlobStore) -> BlobBackend:
    return FileBlobBackend(root_of(settings, store))


async def get_blob_store(db: AsyncSession, name: str) -> BlobStore | None:
    return await db.scalar(select(BlobStore).where(BlobStore.name == name))


async def describe(db: AsyncSession, settings: Settings, store: BlobStore) -> BlobStoreView:
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Blob.size), 0)).where(
                Blob.blob_store_id == store.id
            )
        )
    ).one()
    available = await backend_for(settings, store).available_bytes()
    return BlobStoreView(
        name=store.name,
        type=store.type,
        path=store.config["path"],
        blob_count=count,
        total_bytes=int(total),
        available_bytes=available,
    )


async def list_blob_stores(
    db: AsyncSession, settings: Settings, limit: int, offset: int
) -> tuple[list[BlobStoreView], int]:
    total = await db.scalar(select(func.count()).select_from(BlobStore))
    page = list(
        await db.scalars(select(BlobStore).order_by(BlobStore.name).limit(limit).offset(offset))
    )
    return [await describe(db, settings, store) for store in page], total or 0


async def create_blob_store(
    db: AsyncSession, *, name: str, type: str, path: str | None
) -> BlobStore:
    if type != "file":
        raise _invalid("type", "The only blob store type is file.")
    if path is None:
        path = name
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if not path.strip() or ".." in parts:
        raise _invalid("path", "The path must not be empty or contain '..'.")
    if await get_blob_store(db, name) is not None:
        raise ApiError(409, "conflict", f"A blob store named {name} already exists.")
    store = BlobStore(name=name, type=type, config={"path": path})
    db.add(store)
    await db.flush()
    return store


async def delete_blob_store(db: AsyncSession, store: BlobStore) -> None:
    """Forget a blob store. Its files stay on disk for the operator to remove."""
    user = await db.scalar(
        select(Repository.name).where(Repository.blob_store_id == store.id).limit(1)
    )
    if user is not None:
        raise ApiError(409, "in_use", f"The repository {user} uses this blob store.")
    # With no repository there is no asset, so every remaining blob is unreferenced.
    await db.execute(delete(Blob).where(Blob.blob_store_id == store.id))
    await db.delete(store)
    await db.flush()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/storage -q`
Expected: no failures; `test_blob_stores.py` reports 12 passed and `test_blobs.py` 6 passed.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(storage): add blob store and blob record services"
```

---

### Task 5: Blob store administration API

**Files:**
- Create: `backend/src/megooarti/storage/api.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/storage/test_api.py`

**Interfaces:**
- Consumes: `blob_stores` service (Task 4), `require`, `PageParams`, `Page`, `page`, `get_session`.
- Produces routes under `/api/v1/blob-stores`: `GET ""`, `POST ""`, `GET /{name}`, `DELETE /{name}`. Reading needs `admin:blobstores:read`; changing needs `admin:blobstores:write`. A blob store is returned as `{name, type, path, blob_count, total_bytes, available_bytes}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/storage/test_api.py`:

```python
import pytest

from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic, error_code

STORES = "/api/v1/blob-stores"


async def test_reading_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(STORES)).status_code == 401
    assert (await client.get(STORES, headers=basic("dana", PASSWORD))).status_code == 403


async def test_the_default_store_is_listed_with_its_usage(admin_client):
    body = (await admin_client.get(STORES)).json()

    assert body["total"] == 1
    (store,) = body["items"]
    assert (store["name"], store["type"], store["path"]) == ("default", "file", "default")
    assert (store["blob_count"], store["total_bytes"]) == (0, 0)
    assert store["available_bytes"] > 0


async def test_create_and_get(admin_client):
    created = await admin_client.post(STORES, json={"name": "archive"})

    assert created.status_code == 201
    assert (created.json()["name"], created.json()["path"]) == ("archive", "archive")
    assert (await admin_client.get(f"{STORES}/archive")).json() == created.json()
    assert (await admin_client.get(f"{STORES}/ghost")).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "has space"},
        {"name": ""},
        {"name": "s3-store", "type": "s3"},
        {"name": "escape", "path": "../outside"},
    ],
)
async def test_invalid_stores_are_rejected(admin_client, body):
    response = await admin_client.post(STORES, json=body)
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_duplicate_name_is_a_conflict(admin_client):
    response = await admin_client.post(STORES, json={"name": "default"})
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_delete(admin_client):
    await admin_client.post(STORES, json={"name": "archive"})

    assert (await admin_client.delete(f"{STORES}/archive")).status_code == 204
    assert (await admin_client.get(f"{STORES}/archive")).status_code == 404
    assert (await admin_client.delete(f"{STORES}/archive")).status_code == 404


async def test_a_store_in_use_cannot_be_deleted(admin_client, db, default_store):
    db.add(
        Repository(
            name="files",
            name_key="files",
            format="raw",
            type="hosted",
            blob_store_id=default_store.id,
        )
    )
    await db.commit()

    response = await admin_client.delete(f"{STORES}/default")

    assert (response.status_code, error_code(response)) == (409, "in_use")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/storage/test_api.py -q`
Expected: every test fails with `404` responses.

- [ ] **Step 3: Implement**

`backend/src/megooarti/storage/api.py`:

```python
"""Administration of blob stores."""

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security.authentication import Principal, require
from megooarti.storage import blob_stores
from megooarti.storage.blob_stores import BlobStoreView
from megooarti.storage.models import BlobStore

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/blob-stores", tags=["blob stores"])


class BlobStoreOut(BaseModel):
    name: str
    type: str
    path: str
    blob_count: int
    total_bytes: int
    available_bytes: int | None


class BlobStoreCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    type: str = "file"
    path: str | None = Field(default=None, max_length=1024)


async def _load(db: AsyncSession, name: str) -> BlobStore:
    store = await blob_stores.get_blob_store(db, name)
    if store is None:
        raise ApiError(404, "not_found", "No such blob store.")
    return store


@router.get("", response_model=Page[BlobStoreOut])
async def list_blob_stores(
    request: Request,
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:blobstores:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    settings = request.app.state.settings
    items, total = await blob_stores.list_blob_stores(db, settings, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=BlobStoreOut, status_code=201)
async def create_blob_store(
    body: BlobStoreCreate,
    request: Request,
    principal: Principal = Depends(require("admin:blobstores:write")),
    db: AsyncSession = Depends(get_session),
) -> BlobStoreView:
    store = await blob_stores.create_blob_store(
        db, name=body.name, type=body.type, path=body.path
    )
    view = await blob_stores.describe(db, request.app.state.settings, store)
    await db.commit()
    log.info("blob_store_created", blob_store=store.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=BlobStoreOut)
async def get_blob_store(
    name: str,
    request: Request,
    _: Principal = Depends(require("admin:blobstores:read")),
    db: AsyncSession = Depends(get_session),
) -> BlobStoreView:
    return await blob_stores.describe(db, request.app.state.settings, await _load(db, name))


@router.delete("/{name}", status_code=204)
async def delete_blob_store(
    name: str,
    principal: Principal = Depends(require("admin:blobstores:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    store = await _load(db, name)
    await blob_stores.delete_blob_store(db, store)
    await db.commit()
    log.info("blob_store_deleted", blob_store=name, by=principal.user.username)
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.storage.api import router as blob_stores_router` and include it after the settings router:

```python
    app.include_router(blob_stores_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/storage/test_api.py tests/test_route_guards.py -q`
Expected: no failures; `test_api.py` reports 10 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(storage): add blob store administration API"
```

---

### Task 6: Paths, the format registry and the repository service

**Files:**
- Create: `backend/src/megooarti/repositories/paths.py`
- Create: `backend/src/megooarti/repositories/formats.py`
- Create: `backend/src/megooarti/repositories/raw.py`
- Create: `backend/src/megooarti/repositories/service.py`
- Modify: `backend/src/megooarti/main.py`
- Create: `backend/tests/repositories/__init__.py` (empty)
- Test: `backend/tests/repositories/test_paths.py`
- Test: `backend/tests/repositories/test_formats.py`
- Test: `backend/tests/repositories/test_service.py`

**Interfaces:**
- Consumes: models (Task 2), `blob_stores.get_blob_store`, `blobs.dereference` (Task 4), `ApiError`.
- Produces:
  - `megooarti.repositories.paths.normalise_path(raw: str) -> str` — returns the path unchanged if valid, else raises `ApiError(400, "invalid_path")`; `MAX_PATH_BYTES = 1024`
  - `megooarti.repositories.formats`: `ComponentKey(namespace, name, version="")`; `Format` (base class with `name`, `types`, `validate_config(repository_type, config) -> dict`, `describe_component(path) -> ComponentKey`); `register(format)`, `get_format(name) -> Format | None`, `format_names() -> list[str]`
  - `megooarti.repositories.raw.RawFormat`, registered as `raw` when the module is imported. `megooarti.main` imports it.
  - `megooarti.repositories.service`:
    - `RepositoryView(name, format, type, online, blob_store, url_path, hosted, format_config)` (frozen dataclass)
    - `DEPLOYMENT_POLICIES = ("allow_redeploy", "disable_redeploy", "read_only")`
    - `get_repository(db, name) -> Repository | None` — exact, case-sensitive
    - `describe(db, repository) -> RepositoryView`
    - `list_repositories(db, limit, offset) -> tuple[list[RepositoryView], int]`
    - `create_repository(db, *, name, format, type, online, blob_store, hosted, format_config) -> Repository` — `409 conflict`, `422 validation_error`
    - `update_repository(db, repository, *, online, hosted, format_config) -> None`
    - `delete_repository(db, repository, now) -> None`
  - A repository's `config` is `{"hosted": {"deployment_policy": ...}, "format_config": {...}}`.
  - Only `hosted` repositories can be created in this plan; `proxy` and `group` are rejected with `422` until plan 3b.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/repositories/__init__.py` as an empty file.

`backend/tests/repositories/test_paths.py`:

```python
import pytest

from megooarti.errors import ApiError
from megooarti.repositories.paths import normalise_path


@pytest.mark.parametrize(
    "path",
    [
        "a.txt",
        "a/b/c.tar.gz",
        "ünï/côde ✓.bin",
        "with space/and (parens).txt",
        ".hidden",
        "a/..b/c..",
        "x" * 1024,
    ],
)
def test_valid_paths_are_returned_unchanged(path):
    assert normalise_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/a",
        "a/",
        "a//b",
        "..",
        "../a",
        "a/../b",
        "a/./b",
        ".",
        "a\\b",
        "a\x00b",
        "a\nb",
        "a\x7fb",
        "x" * 1025,
        "é" * 513,
    ],
)
def test_invalid_paths_are_rejected(path):
    with pytest.raises(ApiError) as caught:
        normalise_path(path)
    assert (caught.value.status_code, caught.value.code) == (400, "invalid_path")
```

`backend/tests/repositories/test_formats.py`:

```python
import pytest

from megooarti.errors import ApiError
from megooarti.repositories.formats import ComponentKey, Format, format_names, get_format, register
from megooarti.repositories.raw import RawFormat


def test_raw_is_registered():
    assert isinstance(get_format("raw"), RawFormat)
    assert "raw" in format_names()
    assert get_format("no-such-format") is None


def test_raw_supports_every_repository_type():
    assert get_format("raw").types == {"hosted", "proxy", "group"}


def test_a_format_without_settings_accepts_only_an_empty_object():
    raw = get_format("raw")

    assert raw.validate_config("hosted", {}) == {}
    with pytest.raises(ApiError) as caught:
        raw.validate_config("hosted", {"anything": 1})
    assert caught.value.code == "validation_error"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/guide/intro.txt", ComponentKey("docs/guide", "intro.txt")),
        ("top.txt", ComponentKey("", "top.txt")),
    ],
)
def test_the_generic_component_is_the_file_in_its_directory(path, expected):
    assert get_format("raw").describe_component(path) == expected


def test_a_format_must_have_a_name_to_be_registered():
    with pytest.raises(ValueError):
        register(Format())
```

`backend/tests/repositories/test_service.py`:

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import Asset, Repository
from megooarti.storage.models import Blob, BlobStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def create(db, name="files", **fields):
    fields.setdefault("format", "raw")
    fields.setdefault("type", "hosted")
    fields.setdefault("online", True)
    fields.setdefault("blob_store", "default")
    fields.setdefault("hosted", None)
    fields.setdefault("format_config", {})
    return await service.create_repository(db, name=name, **fields)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def test_create_a_hosted_repository(db):
    repository = await create(db)

    view = await service.describe(db, repository)

    assert view == service.RepositoryView(
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        url_path="/repository/files/",
        hosted={"deployment_policy": "allow_redeploy"},
        format_config={},
    )


async def test_names_are_unique_ignoring_case_but_looked_up_exactly(db):
    await create(db, "Files")

    assert (await error_of(create(db, "files"))).code == "conflict"
    assert await service.get_repository(db, "Files") is not None
    assert await service.get_repository(db, "files") is None


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"format": "cobol"}, "format"),
        ({"type": "proxy"}, "type"),
        ({"type": "group"}, "type"),
        ({"blob_store": "ghost"}, "blob_store"),
        ({"hosted": {"deployment_policy": "sometimes"}}, "hosted.deployment_policy"),
        ({"format_config": {"anything": 1}}, "format_config"),
    ],
)
async def test_invalid_repositories_are_rejected(db, override, field):
    error = await error_of(create(db, **override))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == field


async def test_update_changes_online_and_policy_only(db):
    repository = await create(db)

    await service.update_repository(
        db, repository, online=False, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    view = await service.describe(db, repository)
    assert (view.online, view.hosted) == (False, {"deployment_policy": "read_only"})
    assert (view.name, view.format, view.type, view.blob_store) == (
        "files",
        "raw",
        "hosted",
        "default",
    )


async def test_update_validates_like_create(db):
    repository = await create(db)

    error = await error_of(
        service.update_repository(
            db, repository, online=True, hosted={"deployment_policy": "no"}, format_config={}
        )
    )

    assert error.code == "validation_error"


async def test_delete_removes_content_and_marks_its_blobs_unreferenced(db):
    repository = await create(db)
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id, sha256="a" * 64, md5="b" * 32, sha1="c" * 40, sha512="d" * 128, size=1
    )
    db.add(blob)
    await db.flush()
    db.add(
        Asset(
            repository_id=repository.id,
            path="a.bin",
            blob_id=blob.id,
            content_type="application/octet-stream",
            created_by="dana",
        )
    )
    await db.flush()

    await service.delete_repository(db, repository, NOW)
    await db.refresh(blob)

    assert await service.get_repository(db, "files") is None
    assert await db.scalar(select(Asset.id)) is None
    assert blob.unreferenced_since == NOW


async def test_list_is_paged_in_name_order(db):
    for name in ("zeta", "alpha", "Beta"):
        await create(db, name)

    page, total = await service.list_repositories(db, limit=2, offset=1)

    assert total == 3
    assert [view.name for view in page] == ["Beta", "zeta"]
    assert await db.scalar(select(Repository.name_key).where(Repository.name == "Beta")) == "beta"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories -q`
Expected: three collection errors: `No module named 'megooarti.repositories.paths'`, `'megooarti.repositories.formats'` and `cannot import name 'service'`.

- [ ] **Step 3: Implement path validation**

`backend/src/megooarti/repositories/paths.py`:

```python
"""Validation of paths inside a repository.

These paths are database keys, never file paths: blob files are named by content hash.
The rules exist so that one asset has one spelling and nothing surprising is stored.
"""

from megooarti.errors import ApiError

MAX_PATH_BYTES = 1024


def _invalid(reason: str) -> ApiError:
    return ApiError(400, "invalid_path", f"The path is not valid: {reason}.")


def normalise_path(raw: str) -> str:
    """Return `raw` if it is an acceptable repository path; raise 400 invalid_path if not."""
    if not raw:
        raise _invalid("it is empty")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise _invalid(f"it is longer than {MAX_PATH_BYTES} bytes")
    if "\\" in raw:
        raise _invalid("it contains a backslash")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise _invalid("it contains a control character")
    for segment in raw.split("/"):
        if segment in ("", ".", ".."):
            raise _invalid("it has an empty, '.' or '..' segment")
    return raw
```

- [ ] **Step 4: Implement the format registry and Raw**

`backend/src/megooarti/repositories/formats.py`:

```python
"""The interface every package format implements, and the registry of formats.

The base class is complete, generic, path-addressed behaviour. A format subclasses it,
sets `name`, and overrides only what differs. Formats never touch tables or files:
they work through the repository context they are handed.
"""

from dataclasses import dataclass
from typing import Any

from megooarti.errors import ApiError


@dataclass(frozen=True)
class ComponentKey:
    """What identifies a component (a package) inside a repository."""

    namespace: str
    name: str
    version: str = ""


class Format:
    name: str = ""
    types: frozenset[str] = frozenset({"hosted", "proxy", "group"})

    def validate_config(self, repository_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """Check and return this format's own settings. The generic format has none."""
        if config:
            details = [
                {"field": "format_config", "message": f"The {self.name} format has no settings."}
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        return {}

    def describe_component(self, path: str) -> ComponentKey:
        """Which component a stored path belongs to: the file, in its directory."""
        directory, _, filename = path.rpartition("/")
        return ComponentKey(namespace=directory, name=filename)


_registry: dict[str, Format] = {}


def register(format: Format) -> None:
    if not format.name:
        raise ValueError("a format needs a name before it can be registered")
    _registry[format.name] = format


def get_format(name: str) -> Format | None:
    return _registry.get(name)


def format_names() -> list[str]:
    return sorted(_registry)
```

`backend/src/megooarti/repositories/raw.py`:

```python
"""The Raw format: arbitrary files stored and served by path."""

from megooarti.repositories.formats import Format, register


class RawFormat(Format):
    """Entirely the generic behaviour."""

    name = "raw"


register(RawFormat())
```

In `backend/src/megooarti/main.py`, add this import with the others, so the format is registered whenever the application is loaded:

```python
from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
```

- [ ] **Step 5: Implement the repository service**

`backend/src/megooarti/repositories/service.py`:

```python
"""Repositories: creating, changing, finding and deleting them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.repositories.formats import format_names, get_format
from megooarti.repositories.models import Asset, Repository
from megooarti.storage import blobs
from megooarti.storage.blob_stores import get_blob_store
from megooarti.storage.models import BlobStore

DEPLOYMENT_POLICIES = ("allow_redeploy", "disable_redeploy", "read_only")
# Proxy and group repositories arrive with plan 3b.
_AVAILABLE_TYPES = frozenset({"hosted"})


@dataclass(frozen=True)
class RepositoryView:
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: dict[str, Any] | None
    format_config: dict[str, Any]


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _hosted_settings(hosted: dict[str, Any] | None) -> dict[str, Any]:
    policy = (hosted or {}).get("deployment_policy", "allow_redeploy")
    if policy not in DEPLOYMENT_POLICIES:
        choices = ", ".join(DEPLOYMENT_POLICIES)
        raise _invalid("hosted.deployment_policy", f"Must be one of: {choices}.")
    return {"deployment_policy": policy}


async def get_repository(db: AsyncSession, name: str) -> Repository | None:
    return await db.scalar(select(Repository).where(Repository.name == name))


async def describe(db: AsyncSession, repository: Repository) -> RepositoryView:
    store = None
    if repository.blob_store_id is not None:
        store = await db.scalar(
            select(BlobStore.name).where(BlobStore.id == repository.blob_store_id)
        )
    return RepositoryView(
        name=repository.name,
        format=repository.format,
        type=repository.type,
        online=repository.online,
        blob_store=store,
        url_path=f"/repository/{repository.name}/",
        hosted=repository.config.get("hosted"),
        format_config=repository.config.get("format_config", {}),
    )


async def list_repositories(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[RepositoryView], int]:
    total = await db.scalar(select(func.count()).select_from(Repository))
    page = list(
        await db.scalars(
            select(Repository).order_by(Repository.name_key).limit(limit).offset(offset)
        )
    )
    return [await describe(db, repository) for repository in page], total or 0


async def create_repository(
    db: AsyncSession,
    *,
    name: str,
    format: str,
    type: str,
    online: bool,
    blob_store: str,
    hosted: dict[str, Any] | None,
    format_config: dict[str, Any] | None,
) -> Repository:
    handler = get_format(format)
    if handler is None:
        known = ", ".join(format_names())
        raise _invalid("format", f"Unknown format. Known formats: {known}.")
    if type not in handler.types or type not in _AVAILABLE_TYPES:
        raise _invalid("type", f"{type} repositories are not available for this format.")
    settings = {
        "hosted": _hosted_settings(hosted),
        "format_config": handler.validate_config(type, format_config or {}),
    }
    store = await get_blob_store(db, blob_store)
    if store is None:
        raise _invalid("blob_store", f"Unknown blob store: {blob_store}.")
    taken = await db.scalar(select(Repository.id).where(Repository.name_key == name.lower()))
    if taken is not None:
        raise ApiError(409, "conflict", f"A repository named {name} already exists.")
    repository = Repository(
        name=name,
        name_key=name.lower(),
        format=format,
        type=type,
        online=online,
        blob_store_id=store.id,
        config=settings,
    )
    db.add(repository)
    await db.flush()
    return repository


async def update_repository(
    db: AsyncSession,
    repository: Repository,
    *,
    online: bool,
    hosted: dict[str, Any] | None,
    format_config: dict[str, Any] | None,
) -> None:
    """Replace what can change. Name, format, type and blob store never do."""
    handler = get_format(repository.format)
    repository.config = {
        "hosted": _hosted_settings(hosted),
        "format_config": handler.validate_config(repository.type, format_config or {}),
    }
    repository.online = online
    await db.flush()


async def delete_repository(db: AsyncSession, repository: Repository, now: datetime) -> None:
    """Delete a repository and everything in it. Its blobs become unreferenced."""
    blob_ids = list(
        await db.scalars(select(Asset.blob_id).where(Asset.repository_id == repository.id))
    )
    await db.delete(repository)  # the database removes its components and assets
    await db.flush()
    await blobs.dereference(db, blob_ids, now)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories -q`
Expected: no failures; `test_paths.py` reports 22 passed, `test_formats.py` 6 passed and `test_service.py` 12 passed.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add path rules, the format registry and the repository service"
```

---

### Task 7: Repository administration API

**Files:**
- Create: `backend/src/megooarti/repositories/api.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/repositories/test_api.py`

**Interfaces:**
- Consumes: `service` (Task 6), `require`, `PageParams`, `Page`, `page`, `get_session`, `utcnow`.
- Produces routes under `/api/v1/repositories`: `GET ""`, `POST ""`, `GET /{name}`, `PUT /{name}`, `DELETE /{name}`. Reading needs `admin:repositories:read`; changing needs `admin:repositories:write`. A repository is returned as `{name, format, type, online, blob_store, url_path, hosted, format_config}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_api.py`:

```python
import pytest

from tests.accounts import PASSWORD, basic, error_code

REPOSITORIES = "/api/v1/repositories"
FILES = {"name": "files", "format": "raw", "type": "hosted"}
EXPECTED = {
    "name": "files",
    "format": "raw",
    "type": "hosted",
    "online": True,
    "blob_store": "default",
    "url_path": "/repository/files/",
    "hosted": {"deployment_policy": "allow_redeploy"},
    "format_config": {},
}


async def test_reading_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(REPOSITORIES)).status_code == 401
    assert (await client.get(REPOSITORIES, headers=basic("dana", PASSWORD))).status_code == 403


async def test_create_get_and_list(admin_client):
    created = await admin_client.post(REPOSITORIES, json=FILES)

    assert created.status_code == 201
    assert created.json() == EXPECTED
    assert (await admin_client.get(f"{REPOSITORIES}/files")).json() == EXPECTED
    assert (await admin_client.get(REPOSITORIES)).json()["items"] == [EXPECTED]
    assert (await admin_client.get(f"{REPOSITORIES}/ghost")).status_code == 404


async def test_create_with_explicit_settings(admin_client):
    await admin_client.post("/api/v1/blob-stores", json={"name": "archive"})
    request = {
        **FILES,
        "online": False,
        "blob_store": "archive",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }

    body = (await admin_client.post(REPOSITORIES, json=request)).json()

    assert (body["online"], body["blob_store"]) == (False, "archive")
    assert body["hosted"] == {"deployment_policy": "disable_redeploy"}


@pytest.mark.parametrize(
    "override",
    [
        {"name": "has space"},
        {"name": "a:b"},
        {"name": "star*"},
        {"format": "cobol"},
        {"type": "proxy"},
        {"type": "nonsense"},
        {"blob_store": "ghost"},
        {"hosted": {"deployment_policy": "sometimes"}},
        {"format_config": {"anything": 1}},
    ],
)
async def test_invalid_repositories_are_rejected(admin_client, override):
    response = await admin_client.post(REPOSITORIES, json={**FILES, **override})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_name_that_differs_only_by_case_is_a_conflict(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    response = await admin_client.post(REPOSITORIES, json={**FILES, "name": "FILES"})
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_put_replaces_what_can_change(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    update = {"online": False, "hosted": {"deployment_policy": "read_only"}}

    response = await admin_client.put(f"{REPOSITORIES}/files", json=update)

    assert response.status_code == 200
    assert response.json() == {**EXPECTED, **update}
    assert (await admin_client.put(f"{REPOSITORIES}/ghost", json=update)).status_code == 404


async def test_put_may_repeat_the_fixed_fields_unchanged(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    same = {"online": True, "format": "raw", "type": "hosted", "blob_store": "default"}

    assert (await admin_client.put(f"{REPOSITORIES}/files", json=same)).status_code == 200


@pytest.mark.parametrize(
    "change", [{"format": "maven"}, {"type": "proxy"}, {"blob_store": "archive"}]
)
async def test_put_cannot_change_format_type_or_blob_store(admin_client, change):
    await admin_client.post(REPOSITORIES, json=FILES)

    response = await admin_client.put(f"{REPOSITORIES}/files", json={"online": True, **change})

    assert (response.status_code, error_code(response)) == (409, "immutable")


async def test_delete(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)

    assert (await admin_client.delete(f"{REPOSITORIES}/files")).status_code == 204
    assert (await admin_client.get(f"{REPOSITORIES}/files")).status_code == 404
    assert (await admin_client.delete(f"{REPOSITORIES}/files")).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_api.py -q`
Expected: every test fails with `404` responses.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/api.py`:

```python
"""Administration of repositories."""

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import service
from megooarti.repositories.models import Repository
from megooarti.repositories.service import RepositoryView
from megooarti.security.authentication import Principal, require

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/repositories", tags=["repositories"])

# The same characters as a permission segment, so a name can never shift a permission.
_NAME = r"^[A-Za-z0-9_.-]{1,64}$"


class HostedSettings(BaseModel):
    deployment_policy: Literal["allow_redeploy", "disable_redeploy", "read_only"] = (
        "allow_redeploy"
    )


class RepositoryOut(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: HostedSettings | None
    format_config: dict[str, Any]


class RepositoryCreate(BaseModel):
    name: str = Field(pattern=_NAME)
    format: str
    type: Literal["hosted", "proxy", "group"]
    online: bool = True
    blob_store: str = "default"
    hosted: HostedSettings | None = None
    format_config: dict[str, Any] = {}


class RepositoryUpdate(BaseModel):
    online: bool = True
    hosted: HostedSettings | None = None
    format_config: dict[str, Any] = {}
    # Accepted so a client can send back what it read, but they cannot change.
    format: str | None = None
    type: str | None = None
    blob_store: str | None = None


def _settings(hosted: HostedSettings | None) -> dict[str, Any] | None:
    return None if hosted is None else hosted.model_dump()


async def _load(db: AsyncSession, name: str) -> Repository:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    return repository


@router.get("", response_model=Page[RepositoryOut])
async def list_repositories(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await service.list_repositories(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=RepositoryOut, status_code=201)
async def create_repository(
    body: RepositoryCreate,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await service.create_repository(
        db,
        name=body.name,
        format=body.format,
        type=body.type,
        online=body.online,
        blob_store=body.blob_store,
        hosted=_settings(body.hosted),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    await db.commit()
    log.info("repository_created", repository=repository.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=RepositoryOut)
async def get_repository(
    name: str,
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    return await service.describe(db, await _load(db, name))


@router.put("/{name}", response_model=RepositoryOut)
async def update_repository(
    name: str,
    body: RepositoryUpdate,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await _load(db, name)
    current = await service.describe(db, repository)
    fixed = {"format": current.format, "type": current.type, "blob_store": current.blob_store}
    for field, value in fixed.items():
        sent = getattr(body, field)
        if sent is not None and sent != value:
            raise ApiError(409, "immutable", f"A repository's {field} cannot be changed.")
    await service.update_repository(
        db,
        repository,
        online=body.online,
        hosted=_settings(body.hosted),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    await db.commit()
    log.info("repository_updated", repository=repository.name, by=principal.user.username)
    return view


@router.delete("/{name}", status_code=204)
async def delete_repository(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    await service.delete_repository(db, repository, utcnow())
    await db.commit()
    log.info("repository_deleted", repository=name, by=principal.user.username)
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.repositories.api import router as repositories_router` and include it after the blob stores router:

```python
    app.include_router(repositories_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_api.py tests/test_route_guards.py -q`
Expected: no failures; `test_api.py` reports 19 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add repository administration API"
```

---

### Task 8: Content responses — headers, conditional requests and ranges

**Files:**
- Create: `backend/src/megooarti/repositories/serving.py`
- Test: `backend/tests/repositories/test_serving.py`

**Interfaces:**
- Consumes: `ApiError`.
- Produces, in `megooarti.repositories.serving`:
  - `Servable(sha256, md5, sha1, sha512, size, content_type, last_modified, filename)` (frozen dataclass)
  - `Plan(status: int, headers: dict[str, str], byte_range: tuple[int, int] | None)` — `byte_range` is inclusive; `None` means send no body
  - `plan(method: str, request_headers: Mapping[str, str], item: Servable) -> Plan` — raises `ApiError(416, "range_not_satisfiable")`. `request_headers` must look names up case-insensitively (a Starlette `Headers`).
  - `parse_range(header: str, size: int) -> tuple[int, int] | None` — `None` means "send everything"; raises `RangeNotSatisfiable`

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_serving.py`:

```python
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from starlette.datastructures import Headers

from megooarti.errors import ApiError
from megooarti.repositories.serving import Plan, Servable, plan

ITEM = Servable(
    sha256="a" * 64,
    md5="b" * 32,
    sha1="c" * 40,
    sha512="d" * 128,
    size=1000,
    content_type="text/plain",
    last_modified=datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    filename="notes.txt",
)
ETAG = '"' + "a" * 64 + '"'
MODIFIED = "Fri, 02 Jan 2026 03:04:05 GMT"


def make(method: str = "GET", item: Servable = ITEM, **headers: str) -> Plan:
    return plan(method, Headers({name.replace("_", "-"): value for name, value in headers.items()}), item)


def test_a_plain_get_sends_everything_with_the_full_set_of_headers():
    result = make()

    assert (result.status, result.byte_range) == (200, (0, 999))
    assert result.headers == {
        "Content-Type": "text/plain",
        "Content-Length": "1000",
        "ETag": ETAG,
        "Last-Modified": MODIFIED,
        "Accept-Ranges": "bytes",
        "X-Checksum-Md5": "b" * 32,
        "X-Checksum-Sha1": "c" * 40,
        "X-Checksum-Sha256": "a" * 64,
        "X-Checksum-Sha512": "d" * 128,
        "Content-Disposition": "attachment; filename=\"notes.txt\"; filename*=UTF-8''notes.txt",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }


def test_head_sends_the_headers_and_no_body():
    result = make("HEAD")

    assert (result.status, result.byte_range) == (200, None)
    assert result.headers["Content-Length"] == "1000"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("notes final.txt", "attachment; filename=\"notes_final.txt\"; filename*=UTF-8''notes%20final.txt"),
        ("résumé.pdf", "attachment; filename=\"r_sum_.pdf\"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"),
        ('a"b;c.txt', "attachment; filename=\"a_b_c.txt\"; filename*=UTF-8''a%22b%3Bc.txt"),
        ("✓", "attachment; filename=\"_\"; filename*=UTF-8''%E2%9C%93"),
    ],
)
def test_the_download_name_is_safe_in_a_header(filename, expected):
    assert make(item=replace(ITEM, filename=filename)).headers["Content-Disposition"] == expected


@pytest.mark.parametrize("value", [ETAG, "*", f"W/{ETAG}", f'"other", {ETAG}'])
def test_a_matching_if_none_match_is_not_modified(value):
    result = make(if_none_match=value)

    assert (result.status, result.byte_range) == (304, None)
    assert result.headers["ETag"] == ETAG
    assert "Content-Length" not in result.headers


def test_a_different_if_none_match_sends_the_content():
    assert make(if_none_match='"other"').status == 200


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (MODIFIED, 304),
        ("Sat, 03 Jan 2026 00:00:00 GMT", 304),
        ("Thu, 01 Jan 2026 00:00:00 GMT", 200),
        ("not a date", 200),
    ],
)
def test_if_modified_since(value, status):
    assert make(if_modified_since=value).status == status


def test_if_none_match_takes_priority_over_if_modified_since():
    assert make(if_none_match='"other"', if_modified_since=MODIFIED).status == 200


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("bytes=0-0", (0, 0)),
        ("bytes=10-19", (10, 19)),
        ("bytes=990-", (990, 999)),
        ("bytes=999-999", (999, 999)),
        ("bytes=-10", (990, 999)),
        ("bytes=-5000", (0, 999)),
        ("bytes=500-5000", (500, 999)),
        ("BYTES = 5-6", (5, 6)),
    ],
)
def test_one_satisfiable_range_is_partial_content(value, expected):
    result = make(range=value)
    start, end = expected

    assert (result.status, result.byte_range) == (206, expected)
    assert result.headers["Content-Range"] == f"bytes {start}-{end}/1000"
    assert result.headers["Content-Length"] == str(end - start + 1)


@pytest.mark.parametrize(
    "value", ["bytes=0-1,5-6", "items=0-1", "bytes=abc", "bytes=5-2", "bytes=-", "bytes", ""]
)
def test_a_range_that_is_not_understood_sends_everything(value):
    result = make(range=value)

    assert (result.status, result.byte_range) == (200, (0, 999))
    assert "Content-Range" not in result.headers


@pytest.mark.parametrize("value", ["bytes=1000-", "bytes=2000-3000", "bytes=-0"])
def test_a_range_outside_the_content_cannot_be_satisfied(value):
    with pytest.raises(ApiError) as caught:
        make(range=value)

    assert (caught.value.status_code, caught.value.code) == (416, "range_not_satisfiable")
    assert caught.value.headers == {"Content-Range": "bytes */1000"}


def test_a_range_is_ignored_for_head():
    assert make("HEAD", range="bytes=0-9").status == 200


@pytest.mark.parametrize(("if_range", "status"), [(ETAG, 206), ('"other"', 200)])
def test_if_range_applies_the_range_only_to_the_same_content(if_range, status):
    assert make(range="bytes=0-9", if_range=if_range).status == status


def test_an_empty_file_has_no_body_and_no_satisfiable_range():
    empty = replace(ITEM, size=0)

    result = make(item=empty)

    assert (result.status, result.byte_range, result.headers["Content-Length"]) == (200, None, "0")
    for value in ("bytes=0-0", "bytes=-5", "bytes=0-"):
        with pytest.raises(ApiError):
            make(item=empty, range=value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_serving.py -q`
Expected: collection error, `No module named 'megooarti.repositories.serving'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/serving.py`:

```python
"""Decide how to answer a request for stored content: headers, conditions, ranges.

Pure functions: nothing here touches the database or the blob store.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import quote

from megooarti.errors import ApiError


@dataclass(frozen=True)
class Servable:
    sha256: str
    md5: str
    sha1: str
    sha512: str
    size: int
    content_type: str
    last_modified: datetime
    filename: str


@dataclass(frozen=True)
class Plan:
    status: int
    headers: dict[str, str]
    byte_range: tuple[int, int] | None  # inclusive offsets; None means send no body


class RangeNotSatisfiable(Exception):
    """The requested range lies entirely outside the content."""


def _etag(item: Servable) -> str:
    return f'"{item.sha256}"'


def _disposition(filename: str) -> str:
    # Always a download, never rendered: content shares a site with the admin UI.
    safe = "".join(
        character if character.isascii() and (character.isalnum() or character in "._-") else "_"
        for character in filename
    )
    return f"attachment; filename=\"{safe or '_'}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _base_headers(item: Servable) -> dict[str, str]:
    return {
        "Content-Type": item.content_type,
        "ETag": _etag(item),
        "Last-Modified": format_datetime(item.last_modified.astimezone(UTC), usegmt=True),
        "Accept-Ranges": "bytes",
        "X-Checksum-Md5": item.md5,
        "X-Checksum-Sha1": item.sha1,
        "X-Checksum-Sha256": item.sha256,
        "X-Checksum-Sha512": item.sha512,
        "Content-Disposition": _disposition(item.filename),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }


def _etag_matches(header: str, etag: str) -> bool:
    if header.strip() == "*":
        return True
    return etag in [candidate.strip().removeprefix("W/") for candidate in header.split(",")]


def _not_modified_since(header: str, last_modified: datetime) -> bool:
    try:
        since = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return last_modified.replace(microsecond=0) <= since


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """One `bytes=` range as inclusive offsets, or None for "send everything".

    A header that is malformed, uses another unit, or asks for several ranges is ignored,
    as HTTP allows. Raises RangeNotSatisfiable when the range is outside the content.
    """
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, dash, last = (part.strip() for part in spec.partition("-"))
    if not dash or not (first + last).isdigit():
        return None
    if first == "":
        length = int(last)
        if length == 0 or size == 0:
            raise RangeNotSatisfiable
        return max(size - length, 0), size - 1
    start = int(first)
    if start >= size:
        raise RangeNotSatisfiable
    end = size - 1 if last == "" else min(int(last), size - 1)
    if end < start:
        return None
    return start, end


def plan(method: str, request_headers: Mapping[str, str], item: Servable) -> Plan:
    headers = _base_headers(item)
    etag = _etag(item)

    if_none_match = request_headers.get("if-none-match")
    if if_none_match is not None:
        if _etag_matches(if_none_match, etag):
            return Plan(304, headers, None)
    else:
        since = request_headers.get("if-modified-since")
        if since and _not_modified_since(since, item.last_modified):
            return Plan(304, headers, None)

    byte_range = None
    range_header = request_headers.get("range")
    if_range = request_headers.get("if-range")
    if method == "GET" and range_header and (if_range is None or if_range.strip() == etag):
        try:
            byte_range = parse_range(range_header, item.size)
        except RangeNotSatisfiable:
            raise ApiError(
                416,
                "range_not_satisfiable",
                "The requested range is outside the content.",
                headers={"Content-Range": f"bytes */{item.size}"},
            ) from None

    if byte_range is None:
        headers["Content-Length"] = str(item.size)
        whole = (0, item.size - 1) if method == "GET" and item.size else None
        return Plan(200, headers, whole)

    start, end = byte_range
    headers["Content-Range"] = f"bytes {start}-{end}/{item.size}"
    headers["Content-Length"] = str(end - start + 1)
    return Plan(206, headers, byte_range)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_serving.py -q`
Expected: 38 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add content response planning with conditions and ranges"
```

---

### Task 9: The storage facade

**Files:**
- Create: `backend/src/megooarti/repositories/content.py`
- Create: `backend/tests/repositories/conftest.py`
- Test: `backend/tests/repositories/test_content.py`

**Interfaces:**
- Consumes: `normalise_path`, `Format`, `ComponentKey` (Task 6); `serving.plan`, `Servable` (Task 8); `blobs.record`, `blobs.dereference` (Task 4); `BlobBackend`; `authorize`, `Principal` (Task 1); `utcnow`.
- Produces, in `megooarti.repositories.content`:
  - `RepositoryContext(*, db, settings, repository, principal, format, backend)` with:
    - `.db`, `.settings`, `.repository`, `.principal`, `.format`, `.backend`
    - `permission(action) -> str` — `repository:<format>:<name>:<action>`
    - `async get(path, *, fresh=False) -> Asset | None`
    - `async put(path, chunks, *, content_type=None, expected_size=None, expected_hashes=None, kind="asset") -> tuple[Asset, bool]` — the bool is "created". Checks `add` or `edit` and the deployment policy before reading the body and again before recording. Raises `400 invalid_path`, `400 checksum_mismatch`, `401`, `403 forbidden`, `403 repository_read_only`, `409 redeploy_disabled`.
    - `async delete(path) -> bool` — checks `delete` and the policy; `False` if there was nothing at that path
    - `async respond(path, request) -> Response` — the response for `GET` or `HEAD`; `404 not_found` if absent. Does not check `read`: the route does.
  - None of these commit. `put` and `respond` call `db.commit()` only to release the connection before a body moves; the caller commits the change itself.
- Test helpers (in `tests/repositories/conftest.py`): `someone(*patterns, method="token", username="dana") -> Principal`; `body(data, size=700)` — an async iterator of chunks; fixtures `files` (a committed hosted Raw repository named `files`) and `context_for(repository, principal) -> RepositoryContext`.

- [ ] **Step 1: Write the test helpers**

`backend/tests/repositories/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest

from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Repository
from megooarti.security.authentication import Principal
from megooarti.security.models import User
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore


def someone(*patterns: str, method: str = "token", username: str = "dana") -> Principal:
    """A principal holding exactly these patterns, without touching the database."""
    user = User(username=username, display_name=username.title(), must_change_password=False)
    return Principal(user, method, frozenset(patterns))


async def body(data: bytes, size: int = 700) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.fixture
async def files(db) -> Repository:
    repository = await service.create_repository(
        db,
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=None,
        format_config={},
    )
    await db.commit()
    return repository


@pytest.fixture
def context_for(db, settings):
    async def make(repository: Repository, principal: Principal | None) -> RepositoryContext:
        store = await db.get(BlobStore, repository.blob_store_id)
        return RepositoryContext(
            db=db,
            settings=settings,
            repository=repository,
            principal=principal,
            format=get_format(repository.format),
            backend=backend_for(settings, store),
        )

    return make
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/repositories/test_content.py`:

```python
import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import StreamingResponse

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from megooarti.storage.models import Blob
from tests.repositories.conftest import body, someone

EVERYTHING = someone("repository:raw:files")
HELLO = b"hello, world"


def request(method: str = "GET", **headers: str) -> Request:
    raw = [(name.replace("_", "-").encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw})


async def read(response) -> bytes:
    if isinstance(response, StreamingResponse):
        return b"".join([chunk async for chunk in response.body_iterator])
    return response.body


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def temporary_files(settings) -> list:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


async def test_put_stores_a_new_asset_with_its_component_and_blob(db, files, context_for):
    context = await context_for(files, EVERYTHING)

    asset, created = await context.put("docs/a.txt", body(HELLO))

    assert created is True
    assert (asset.path, asset.content_type, asset.kind) == ("docs/a.txt", "text/plain", "asset")
    assert asset.created_by == "dana"
    component = await db.get(Component, asset.component_id)
    assert (component.namespace, component.name, component.version) == ("docs", "a.txt", "")
    blob = await db.get(Blob, asset.blob_id)
    assert (blob.sha256, blob.size) == (hashlib.sha256(HELLO).hexdigest(), len(HELLO))
    assert await context.backend.exists(blob.sha256)
    assert temporary_files(context.settings) == []


async def test_put_replaces_an_existing_asset_and_releases_its_old_content(
    db, files, context_for
):
    context = await context_for(files, EVERYTHING)
    first, _ = await context.put("a.bin", body(b"first"))
    first_id, first_blob, first_updated = first.id, first.blob_id, first.updated_at

    second, created = await context.put("a.bin", body(b"second"))

    assert created is False
    assert second.id == first_id
    assert second.blob_id != first_blob
    assert second.updated_at > first_updated
    assert await count(db, Asset) == 1
    old = await db.get(Blob, first_blob, populate_existing=True)
    assert old.unreferenced_since is not None


async def test_the_same_content_at_two_paths_is_stored_once(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    one, _ = await context.put("one.bin", body(HELLO))
    two, _ = await context.put("two.bin", body(HELLO))

    assert one.blob_id == two.blob_id
    assert await count(db, Blob) == 1

    await context.delete("one.bin")

    shared = await db.get(Blob, two.blob_id, populate_existing=True)
    assert shared.unreferenced_since is None


@pytest.mark.parametrize(
    ("declared", "path", "expected"),
    [
        ("application/json", "a.bin", "application/json"),
        ("text/plain; charset=utf-8", "a.bin", "text/plain; charset=utf-8"),
        (None, "a.txt", "text/plain"),
        (None, "a.unknownextension", "application/octet-stream"),
        ("not a type", "a.txt", "text/plain"),
        ("text/html\r\nX-Evil: 1", "a.bin", "application/octet-stream"),
        ("x" * 300 + "/y", "a.bin", "application/octet-stream"),
    ],
)
async def test_content_type_is_the_declared_one_only_if_well_formed(
    files, context_for, declared, path, expected
):
    context = await context_for(files, EVERYTHING)

    asset, _ = await context.put(path, body(HELLO), content_type=declared)

    assert asset.content_type == expected


@pytest.mark.parametrize(
    "expectations",
    [
        {"expected_size": len(HELLO) + 1},
        {"expected_hashes": {"md5": "0" * 32}},
        {"expected_hashes": {"sha1": "0" * 40}},
        {"expected_hashes": {"sha256": "0" * 64}},
    ],
)
async def test_a_size_or_checksum_mismatch_stores_nothing(
    db, files, context_for, expectations
):
    context = await context_for(files, EVERYTHING)

    error = await error_of(context.put("a.bin", body(HELLO), **expectations))

    assert (error.status_code, error.code) == (400, "checksum_mismatch")
    assert await count(db, Asset) == 0
    assert temporary_files(context.settings) == []


async def test_matching_size_and_checksums_are_accepted_in_any_case(files, context_for):
    context = await context_for(files, EVERYTHING)
    hashes = {
        "md5": hashlib.md5(HELLO).hexdigest().upper(),
        "sha1": hashlib.sha1(HELLO).hexdigest(),
        "sha256": f" {hashlib.sha256(HELLO).hexdigest()} ",
    }

    _, created = await context.put(
        "a.bin", body(HELLO), expected_size=len(HELLO), expected_hashes=hashes
    )

    assert created is True


async def test_an_interrupted_upload_stores_nothing(db, files, context_for):
    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise ConnectionError("the client went away")

    context = await context_for(files, EVERYTHING)

    with pytest.raises(ConnectionError):
        await context.put("a.bin", broken())

    assert await count(db, Asset) == 0
    assert temporary_files(context.settings) == []


async def test_no_database_connection_is_held_while_the_body_arrives(db, files, context_for):
    in_transaction = []

    async def watching() -> AsyncIterator[bytes]:
        in_transaction.append(db.in_transaction())
        yield HELLO

    context = await context_for(files, EVERYTHING)
    await context.put("a.bin", watching())

    assert in_transaction == [False]


@pytest.mark.parametrize(
    ("principal", "may_create", "may_replace"),
    [
        (someone("repository:raw:files:add"), True, False),
        (someone("repository:raw:files:edit"), False, True),
        (someone("repository:raw:files:read"), False, False),
        (someone("repository:raw:other"), False, False),
    ],
)
async def test_storing_needs_add_for_a_new_path_and_edit_for_an_existing_one(
    files, context_for, principal, may_create, may_replace
):
    seeded = await context_for(files, EVERYTHING)
    await seeded.put("existing.bin", body(b"old"))
    context = await context_for(files, principal)

    if may_create:
        assert (await context.put("new.bin", body(HELLO)))[1] is True
    else:
        assert (await error_of(context.put("new.bin", body(HELLO)))).code == "forbidden"
    if may_replace:
        assert (await context.put("existing.bin", body(HELLO)))[1] is False
    else:
        assert (await error_of(context.put("existing.bin", body(HELLO)))).code == "forbidden"


async def test_storing_without_a_principal_is_unauthorized_with_a_basic_challenge(
    files, context_for
):
    context = await context_for(files, None)

    error = await error_of(context.put("a.bin", body(HELLO)))

    assert error.status_code == 401
    assert error.headers == {"WWW-Authenticate": 'Basic realm="MegooArti"'}


async def test_a_read_only_repository_refuses_changes(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    await context.put("a.bin", body(HELLO))
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    stored = await error_of(context.put("b.bin", body(HELLO)))
    deleted = await error_of(context.delete("a.bin"))

    assert (stored.status_code, stored.code) == (403, "repository_read_only")
    assert (deleted.status_code, deleted.code) == (403, "repository_read_only")


async def test_disable_redeploy_allows_a_path_to_be_written_once(db, files, context_for):
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "disable_redeploy"}, format_config={}
    )
    context = await context_for(files, EVERYTHING)

    await context.put("a.bin", body(b"first"))
    error = await error_of(context.put("a.bin", body(b"second")))

    assert (error.status_code, error.code) == (409, "redeploy_disabled")
    assert await context.delete("a.bin") is True


@pytest.mark.parametrize("path", ["../escape", "a//b", ""])
async def test_an_invalid_path_is_rejected_everywhere(files, context_for, path):
    context = await context_for(files, EVERYTHING)

    for call in (context.put(path, body(HELLO)), context.delete(path), context.respond(path, request())):
        error = await error_of(call)
        assert (error.status_code, error.code) == (400, "invalid_path")


async def test_delete_removes_the_asset_its_component_and_releases_the_content(
    db, files, context_for
):
    context = await context_for(files, EVERYTHING)
    asset, _ = await context.put("docs/a.txt", body(HELLO))
    blob_id = asset.blob_id

    assert await context.delete("docs/a.txt") is True

    assert await count(db, Asset) == 0
    assert await count(db, Component) == 0
    blob = await db.get(Blob, blob_id, populate_existing=True)
    assert blob.unreferenced_since is not None
    assert await context.delete("docs/a.txt") is False


async def test_delete_needs_the_delete_permission(files, context_for):
    seeded = await context_for(files, EVERYTHING)
    await seeded.put("a.bin", body(HELLO))
    context = await context_for(files, someone("repository:raw:files:add"))

    assert (await error_of(context.delete("a.bin"))).code == "forbidden"


async def test_respond_sends_the_content_with_its_headers(files, context_for):
    context = await context_for(files, EVERYTHING)
    await context.put("docs/a.txt", body(HELLO))

    response = await context.respond("docs/a.txt", request())

    assert response.status_code == 200
    assert await read(response) == HELLO
    assert response.headers["Content-Length"] == str(len(HELLO))
    assert response.headers["ETag"] == f'"{hashlib.sha256(HELLO).hexdigest()}"'
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="a.txt"')


async def test_respond_honours_ranges_conditions_and_head(files, context_for):
    context = await context_for(files, EVERYTHING)
    await context.put("a.bin", body(HELLO))
    etag = f'"{hashlib.sha256(HELLO).hexdigest()}"'

    partial = await context.respond("a.bin", request(range="bytes=7-11"))
    unchanged = await context.respond("a.bin", request(if_none_match=etag))
    head = await context.respond("a.bin", request("HEAD"))

    assert (partial.status_code, await read(partial)) == (206, b"world")
    assert partial.headers["Content-Range"] == f"bytes 7-11/{len(HELLO)}"
    assert (unchanged.status_code, await read(unchanged)) == (304, b"")
    assert (head.status_code, await read(head)) == (200, b"")
    assert head.headers["Content-Length"] == str(len(HELLO))


async def test_respond_for_a_missing_path_is_not_found(files, context_for):
    context = await context_for(files, EVERYTHING)

    error = await error_of(context.respond("nothing/here.bin", request()))

    assert (error.status_code, error.code) == (404, "not_found")


async def test_a_download_is_noted_at_most_once_an_hour_and_never_for_head(
    db, files, context_for
):
    context = await context_for(files, EVERYTHING)
    asset, _ = await context.put("a.bin", body(HELLO))
    updated = asset.updated_at

    await context.respond("a.bin", request("HEAD"))
    assert asset.last_downloaded_at is None

    await context.respond("a.bin", request())
    first = asset.last_downloaded_at
    await context.respond("a.bin", request())
    assert first is not None
    assert asset.last_downloaded_at == first

    asset.last_downloaded_at = first - timedelta(hours=2)
    await db.flush()
    await context.respond("a.bin", request())

    assert asset.last_downloaded_at > first - timedelta(hours=2)
    assert asset.updated_at == updated
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_content.py -q`
Expected: collection error in `tests/repositories/conftest.py`, `No module named 'megooarti.repositories.content'`.

- [ ] **Step 4: Implement**

`backend/src/megooarti/repositories/content.py`:

```python
"""The storage facade formats work through.

It enforces the add, edit and delete permissions and the deployment policy, so a format
cannot bypass them, and it is the only code that ties assets to blobs.
"""

import hashlib
import mimetypes
import re
from collections.abc import AsyncIterator
from datetime import timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import serving
from megooarti.repositories.formats import ComponentKey, Format
from megooarti.repositories.models import Asset, Component, Repository
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import Principal, authorize
from megooarti.storage import blobs
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.models import Blob

# First key of the two-key advisory lock; the second is derived from what is locked.
_LOCK_NAMESPACE = 0x4D48
_DOWNLOAD_NOTE_INTERVAL = timedelta(hours=1)
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(;[\x20-\x7e]*)?")


def _media_type(declared: str | None, path: str) -> str:
    """The declared type if it is a well-formed media type, else a guess from the name."""
    if declared is not None:
        declared = declared.strip()
        if len(declared) <= 255 and _MEDIA_TYPE.fullmatch(declared):
            return declared
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _verify(
    staged: StagedBlob, expected_size: int | None, expected_hashes: dict[str, str] | None
) -> None:
    if expected_size is not None and staged.size != expected_size:
        raise ApiError(
            400,
            "checksum_mismatch",
            f"Received {staged.size} bytes but {expected_size} were declared.",
        )
    for algorithm, expected in (expected_hashes or {}).items():
        if getattr(staged, algorithm) != expected.strip().lower():
            raise ApiError(
                400, "checksum_mismatch", f"The {algorithm} checksum does not match the content."
            )


class RepositoryContext:
    """One request's view of one repository."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        repository: Repository,
        principal: Principal | None,
        format: Format,
        backend: BlobBackend,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository
        self.principal = principal
        self.format = format
        self.backend = backend

    def permission(self, action: str) -> str:
        return f"repository:{self.repository.format}:{self.repository.name}:{action}"

    async def _lock(self, kind: str, key: str) -> None:
        """Serialise work on one path or component until this transaction ends."""
        digest = hashlib.sha256(f"{self.repository.id}:{kind}:{key}".encode()).digest()
        number = int.from_bytes(digest[:4], "big", signed=True)
        await self.db.execute(
            text(f"SELECT pg_advisory_xact_lock({_LOCK_NAMESPACE}, {number})")
        )

    async def get(self, path: str, *, fresh: bool = False) -> Asset | None:
        statement = select(Asset).where(
            Asset.repository_id == self.repository.id, Asset.path == path
        )
        if fresh:  # reread from the database even if this session already loaded it
            statement = statement.execution_options(populate_existing=True)
        return await self.db.scalar(statement)

    def _check_policy(self, *, replacing: bool) -> None:
        policy = self.repository.config.get("hosted", {}).get("deployment_policy")
        if policy == "read_only":
            raise ApiError(403, "repository_read_only", "This repository is read-only.")
        if replacing and policy == "disable_redeploy":
            raise ApiError(
                409, "redeploy_disabled", "This repository does not allow a path to be replaced."
            )

    def _check_may_store(self, existing: Asset | None) -> None:
        action = "add" if existing is None else "edit"
        authorize(self.principal, self.permission(action), scheme="Basic")
        self._check_policy(replacing=existing is not None)

    async def _component(self, key: ComponentKey) -> Component:
        await self._lock("component", f"{key.namespace}\x00{key.name}\x00{key.version}")
        component = await self.db.scalar(
            select(Component).where(
                Component.repository_id == self.repository.id,
                Component.namespace == key.namespace,
                Component.name == key.name,
                Component.version == key.version,
            )
        )
        if component is None:
            component = Component(
                repository_id=self.repository.id,
                namespace=key.namespace,
                name=key.name,
                version=key.version,
            )
            self.db.add(component)
            await self.db.flush()
        return component

    async def put(
        self,
        path: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        expected_size: int | None = None,
        expected_hashes: dict[str, str] | None = None,
        kind: str = "asset",
    ) -> tuple[Asset, bool]:
        """Store content at a path. Returns the asset and whether it is new.

        The caller commits. Permission and policy are checked before the body is read,
        so a refused upload is refused early, and again before recording, because the
        path may have been written while the body arrived.
        """
        path = normalise_path(path)
        self._check_may_store(await self.get(path))
        await self.db.commit()  # give the connection back while the body arrives

        staged = await self.backend.stage(chunks)
        try:
            _verify(staged, expected_size, expected_hashes)
            await self._lock("path", path)
            existing = await self.get(path, fresh=True)
            self._check_may_store(existing)
            blob = await blobs.record(
                self.db, self.backend, self.repository.blob_store_id, staged
            )
        except BaseException:
            await self.backend.discard(staged)
            raise

        now = utcnow()
        media_type = _media_type(content_type, path)
        if existing is None:
            component = await self._component(self.format.describe_component(path))
            asset = Asset(
                repository_id=self.repository.id,
                component_id=component.id,
                path=path,
                blob_id=blob.id,
                content_type=media_type,
                kind=kind,
                created_by=self.principal.user.username,
            )
            self.db.add(asset)
            await self.db.flush()
            return asset, True

        previous = existing.blob_id
        existing.blob_id = blob.id
        existing.content_type = media_type
        existing.updated_at = now
        existing.last_verified_at = None
        await self.db.flush()
        if previous != blob.id:
            await blobs.dereference(self.db, [previous], now)
        return existing, False

    async def delete(self, path: str) -> bool:
        """Remove what is at a path. False if there was nothing. The caller commits."""
        path = normalise_path(path)
        authorize(self.principal, self.permission("delete"), scheme="Basic")
        self._check_policy(replacing=False)
        await self._lock("path", path)
        asset = await self.get(path, fresh=True)
        if asset is None:
            return False
        blob_id, component_id = asset.blob_id, asset.component_id
        await self.db.delete(asset)
        await self.db.flush()
        if component_id is not None:
            remaining = await self.db.scalar(
                select(Asset.id).where(Asset.component_id == component_id).limit(1)
            )
            if remaining is None:
                await self.db.execute(delete(Component).where(Component.id == component_id))
        await blobs.dereference(self.db, [blob_id], utcnow())
        return True

    async def respond(self, path: str, request: Request) -> Response:
        """The response to a GET or HEAD for a path. The caller has checked `read`."""
        path = normalise_path(path)
        found = (
            await self.db.execute(
                select(Asset, Blob)
                .join(Blob, Blob.id == Asset.blob_id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if found is None:
            raise ApiError(404, "not_found", "No such file.")
        asset, blob = found
        item = serving.Servable(
            sha256=blob.sha256,
            md5=blob.md5,
            sha1=blob.sha1,
            sha512=blob.sha512,
            size=blob.size,
            content_type=asset.content_type,
            last_modified=asset.updated_at,
            filename=path.rpartition("/")[2],
        )
        plan = serving.plan(request.method, request.headers, item)

        now = utcnow()
        noted = asset.last_downloaded_at
        if plan.byte_range is not None and (
            noted is None or now - noted >= _DOWNLOAD_NOTE_INTERVAL
        ):
            asset.last_downloaded_at = now
        await self.db.commit()  # give the connection back before the body is sent

        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return StreamingResponse(
            self.backend.open(blob.sha256, start, end),
            status_code=plan.status,
            headers=plan.headers,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_content.py -q`
Expected: 33 passed.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add the storage facade with permissions and deployment policy"
```

---

### Task 10: The repository content route and hosted Raw

**Files:**
- Modify: `backend/src/megooarti/repositories/formats.py` (replace the whole file)
- Create: `backend/src/megooarti/repositories/routes.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/repositories/test_raw_hosted.py`

**Interfaces:**
- Consumes: `RepositoryContext` (Task 9); `service.get_repository` (Task 6); `backend_for` (Task 4); `client_principal`, `authorize`, `unauthorized` (Task 1).
- Produces:
  - `Format.handle_hosted(context, request, path) -> Response` — generic behaviour: `GET` / `HEAD` serve, `PUT` stores (`201` new, `204` replaced), `DELETE` removes (`204`), anything else `405` with an `Allow` header. It commits its own changes.
  - `megooarti.repositories.routes.router` with one route, `/repository/{name}/{path:path}`, for `GET`, `HEAD`, `PUT`, `POST`, `PATCH` and `DELETE`. It is mounted without the `/api/v1` prefix and is not in the OpenAPI document.
  - Order of checks: authenticate (Basic challenge) → repository exists (`404`) → `read` for `GET`/`HEAD`, or "someone is identified" for other methods (the facade checks `add`, `edit`, `delete`) → online (`503 repository_offline`) → dispatch.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_raw_hosted.py`:

```python
import hashlib
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.models import Asset
from megooarti.security import roles
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code

URL = "/repository/files/docs/a.txt"
HELLO = b"hello, world"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def test_put_then_get_returns_the_same_bytes_with_content_headers(client, files, root):
    stored = await client.put(URL, content=HELLO, headers=root)
    fetched = await client.get(URL, headers=root)

    assert (stored.status_code, stored.content) == (201, b"")
    assert (fetched.status_code, fetched.content) == (200, HELLO)
    digest = hashlib.sha256(HELLO).hexdigest()
    assert fetched.headers["ETag"] == f'"{digest}"'
    assert fetched.headers["X-Checksum-Sha256"] == digest
    assert fetched.headers["X-Checksum-Sha1"] == hashlib.sha1(HELLO).hexdigest()
    assert fetched.headers["Content-Type"] == "text/plain"
    assert fetched.headers["Content-Length"] == str(len(HELLO))
    assert fetched.headers["Content-Disposition"].startswith('attachment; filename="a.txt"')
    assert fetched.headers["X-Content-Type-Options"] == "nosniff"
    assert fetched.headers["Content-Security-Policy"] == "sandbox"


async def test_put_to_an_existing_path_replaces_it(client, files, root):
    await client.put(URL, content=b"first", headers=root)

    replaced = await client.put(URL, content=b"second", headers=root)

    assert replaced.status_code == 204
    assert (await client.get(URL, headers=root)).content == b"second"


async def test_head_sends_headers_only(client, files, root):
    await client.put(URL, content=HELLO, headers=root)

    response = await client.head(URL, headers=root)

    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["Content-Length"] == str(len(HELLO))


async def test_missing_things_are_not_found(client, files, root):
    missing_file = await client.get(URL, headers=root)
    missing_repository = await client.get("/repository/ghost/a.txt", headers=root)

    assert (missing_file.status_code, error_code(missing_file)) == (404, "not_found")
    assert (missing_repository.status_code, error_code(missing_repository)) == (404, "not_found")


async def test_delete(client, files, root):
    await client.put(URL, content=HELLO, headers=root)

    assert (await client.delete(URL, headers=root)).status_code == 204
    assert (await client.get(URL, headers=root)).status_code == 404
    assert (await client.delete(URL, headers=root)).status_code == 404


async def test_ranges_and_conditions(client, files, root):
    await client.put(URL, content=HELLO, headers=root)
    etag = (await client.head(URL, headers=root)).headers["ETag"]

    partial = await client.get(URL, headers={**root, "Range": "bytes=7-"})
    outside = await client.get(URL, headers={**root, "Range": "bytes=50-60"})
    unchanged = await client.get(URL, headers={**root, "If-None-Match": etag})

    assert (partial.status_code, partial.content) == (206, b"world")
    assert partial.headers["Content-Range"] == f"bytes 7-11/{len(HELLO)}"
    assert (outside.status_code, error_code(outside)) == (416, "range_not_satisfiable")
    assert outside.headers["Content-Range"] == f"bytes */{len(HELLO)}"
    assert (unchanged.status_code, unchanged.content) == (304, b"")


async def test_a_large_streamed_upload_round_trips(client, files, root):
    block = bytes(range(256)) * 4096  # 1 MiB
    blocks = 5

    async def stream() -> AsyncIterator[bytes]:
        for _ in range(blocks):
            yield block

    stored = await client.put("/repository/files/big.bin", content=stream(), headers=root)
    fetched = await client.get("/repository/files/big.bin", headers=root)

    assert stored.status_code == 201
    assert fetched.headers["Content-Length"] == str(blocks * len(block))
    assert hashlib.sha256(fetched.content).hexdigest() == hashlib.sha256(block * blocks).hexdigest()


async def test_a_declared_checksum_must_match(client, files, root):
    wrong = await client.put(
        URL, content=HELLO, headers={**root, "X-Checksum-Sha256": "0" * 64}
    )
    right = await client.put(
        URL, content=HELLO, headers={**root, "X-Checksum-Sha1": hashlib.sha1(HELLO).hexdigest()}
    )

    assert (wrong.status_code, error_code(wrong)) == (400, "checksum_mismatch")
    assert right.status_code == 201


async def test_the_declared_content_type_is_kept(client, files, root):
    await client.put(URL, content=b"{}", headers={**root, "Content-Type": "application/json"})

    assert (await client.get(URL, headers=root)).headers["Content-Type"] == "application/json"


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_other_methods_are_not_allowed(client, files, root, method):
    response = await client.request(method, URL, content=HELLO, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, PUT, DELETE"


@pytest.mark.parametrize("path", ["a//b.txt", "trailing/", ""])
async def test_an_invalid_path_is_a_bad_request(client, files, root, path):
    response = await client.get(f"/repository/files/{path}", headers=root)
    assert (response.status_code, error_code(response)) == (400, "invalid_path")


async def test_no_credentials_gets_a_basic_challenge(client, files):
    for response in (await client.get(URL), await client.put(URL, content=HELLO)):
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
        assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_wrong_credentials_get_a_basic_challenge(client, files):
    response = await client.get(URL, headers=basic("nobody", "wrong password"))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_a_token_can_be_used_as_bearer_or_as_a_basic_password(
    client, files, make_user, make_token
):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    assert (await client.put(URL, content=HELLO, headers=bearer(token))).status_code == 201
    assert (await client.get(URL, headers=basic("root", token))).content == HELLO


async def test_each_action_needs_its_own_permission(client, files, root, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:raw:files:read"], [])
    await roles.create_role(db, "writers", "", ["repository:raw:files:add"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    await make_user("wes", roles=["writers"])
    reader, writer = basic("rae", PASSWORD), basic("wes", PASSWORD)

    by_reader = await client.put(URL, content=HELLO, headers=reader)
    by_writer = await client.put(URL, content=HELLO, headers=writer)
    replaced = await client.put(URL, content=b"again", headers=writer)
    read_by_writer = await client.get(URL, headers=writer)
    deleted = await client.delete(URL, headers=writer)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert by_writer.status_code == 201
    assert (replaced.status_code, error_code(replaced)) == (403, "forbidden")
    assert (read_by_writer.status_code, error_code(read_by_writer)) == (403, "forbidden")
    assert (deleted.status_code, error_code(deleted)) == (403, "forbidden")
    assert (await client.get(URL, headers=reader)).content == HELLO


async def test_a_permission_on_another_repository_does_not_apply(client, files, make_user, db):
    await roles.create_role(db, "elsewhere", "", ["repository:raw:other"], [])
    await db.commit()
    await make_user("eli", roles=["elsewhere"])

    response = await client.get(URL, headers=basic("eli", PASSWORD))

    assert (response.status_code, error_code(response)) == (403, "forbidden")


async def test_anonymous_access_allows_reading_but_not_writing(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    assert (await client.get(URL)).status_code == 401

    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    assert (await client.get(URL)).content == HELLO
    assert (await client.put(URL, content=b"defaced")).status_code == 401
    assert (await client.delete(URL)).status_code == 401


async def test_a_signed_in_user_without_roles_can_read_public_content(
    client, files, root, make_user, db
):
    await client.put(URL, content=HELLO, headers=root)
    await make_user("dana")
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    assert (await client.get(URL, headers=basic("dana", PASSWORD))).content == HELLO


async def test_a_browser_session_needs_the_csrf_token_to_upload(admin_client, files):
    refused = await admin_client.put(URL, content=HELLO, headers={"X-CSRF-Token": "wrong"})
    allowed = await admin_client.put(URL, content=HELLO)

    assert (refused.status_code, error_code(refused)) == (403, "csrf_failed")
    assert allowed.status_code == 201
    assert (await admin_client.get(URL)).content == HELLO


async def test_an_offline_repository_is_unavailable(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    await service.update_repository(db, files, online=False, hosted=None, format_config={})
    await db.commit()

    response = await client.get(URL, headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")


async def test_policies_apply_through_the_route(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "disable_redeploy"}, format_config={}
    )
    await db.commit()

    response = await client.put(URL, content=b"again", headers=root)

    assert (response.status_code, error_code(response)) == (409, "redeploy_disabled")
    assert (await client.get(URL, headers=root)).content == HELLO


async def test_a_download_is_recorded_on_the_asset(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    await client.head(URL, headers=root)
    assert await db.scalar(select(Asset.last_downloaded_at)) is None

    await client.get(URL, headers=root)

    assert await db.scalar(select(Asset.last_downloaded_at)) is not None


async def test_the_content_route_is_not_in_the_api_document(client):
    document = (await client.get("/api/v1/openapi.json")).json()
    assert not [path for path in document["paths"] if path.startswith("/repository")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_raw_hosted.py -q`
Expected: every test except `test_the_content_route_is_not_in_the_api_document` fails, with `404` responses that are not in the expected shape.

- [ ] **Step 3: Give the format its generic hosted behaviour**

Replace `backend/src/megooarti/repositories/formats.py` with:

```python
"""The interface every package format implements, and the registry of formats.

The base class is complete, generic, path-addressed behaviour. A format subclasses it,
sets `name`, and overrides only what differs. Formats never touch tables or files:
they work through the repository context they are handed.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError

if TYPE_CHECKING:
    from megooarti.repositories.content import RepositoryContext

_CHECKSUM_HEADERS = {"md5": "X-Checksum-Md5", "sha1": "X-Checksum-Sha1", "sha256": "X-Checksum-Sha256"}


@dataclass(frozen=True)
class ComponentKey:
    """What identifies a component (a package) inside a repository."""

    namespace: str
    name: str
    version: str = ""


def _declared_size(request: Request) -> int | None:
    value = request.headers.get("Content-Length", "")
    return int(value) if value.isdigit() else None


def _declared_hashes(request: Request) -> dict[str, str]:
    return {
        algorithm: request.headers[header]
        for algorithm, header in _CHECKSUM_HEADERS.items()
        if header in request.headers
    }


class Format:
    name: str = ""
    types: frozenset[str] = frozenset({"hosted", "proxy", "group"})

    def validate_config(self, repository_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """Check and return this format's own settings. The generic format has none."""
        if config:
            details = [
                {"field": "format_config", "message": f"The {self.name} format has no settings."}
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        return {}

    def describe_component(self, path: str) -> ComponentKey:
        """Which component a stored path belongs to: the file, in its directory."""
        directory, _, filename = path.rpartition("/")
        return ComponentKey(namespace=directory, name=filename)

    async def handle_hosted(
        self, context: "RepositoryContext", request: Request, path: str
    ) -> Response:
        """Answer a request to a hosted repository. The route has checked `read`."""
        if request.method in ("GET", "HEAD"):
            return await context.respond(path, request)
        if request.method == "PUT":
            _, created = await context.put(
                path,
                request.stream(),
                content_type=request.headers.get("Content-Type"),
                expected_size=_declared_size(request),
                expected_hashes=_declared_hashes(request),
            )
            await context.db.commit()
            return Response(status_code=201 if created else 204)
        if request.method == "DELETE":
            if not await context.delete(path):
                raise ApiError(404, "not_found", "No such file.")
            await context.db.commit()
            return Response(status_code=204)
        raise ApiError(
            405,
            "method_not_allowed",
            "This repository accepts GET, HEAD, PUT and DELETE.",
            headers={"Allow": "GET, HEAD, PUT, DELETE"},
        )


_registry: dict[str, Format] = {}


def register(format: Format) -> None:
    if not format.name:
        raise ValueError("a format needs a name before it can be registered")
    _registry[format.name] = format


def get_format(name: str) -> Format | None:
    return _registry.get(name)


def format_names() -> list[str]:
    return sorted(_registry)
```

- [ ] **Step 4: Add the route**

`backend/src/megooarti/repositories/routes.py`:

```python
"""Requests for repository content: /repository/{name}/{path}.

Authentication and the `read` check happen here, before any format code runs. The
storage facade checks `add`, `edit` and `delete` at the moment of each operation.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import get_format
from megooarti.security.authentication import (
    Principal,
    authorize,
    client_principal,
    unauthorized,
)
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore

log = structlog.get_logger(__name__)

router = APIRouter()

_METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]


@router.api_route("/repository/{name}/{path:path}", methods=_METHODS, include_in_schema=False)
async def repository_content(
    name: str,
    path: str,
    request: Request,
    principal: Principal | None = Depends(client_principal),
    db: AsyncSession = Depends(get_session),
) -> Response:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    settings = request.app.state.settings
    store = await db.get(BlobStore, repository.blob_store_id)
    context = RepositoryContext(
        db=db,
        settings=settings,
        repository=repository,
        principal=principal,
        format=get_format(repository.format),
        backend=backend_for(settings, store),
    )

    if request.method in ("GET", "HEAD"):
        authorize(principal, context.permission("read"), scheme="Basic")
    elif principal is None:
        raise unauthorized(scheme="Basic")
    if not repository.online:
        raise ApiError(503, "repository_offline", "This repository is offline.")

    try:
        return await context.format.handle_hosted(context, request, path)
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was stored; nobody is left to answer.
        log.info("upload_interrupted", repository=name, path=path)
        return Response(status_code=400)
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.repositories.routes import router as content_router` and include it after the repositories router, **without** the API prefix:

```python
    app.include_router(content_router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_raw_hosted.py tests/test_route_guards.py -q`
Expected: no failures; `test_raw_hosted.py` reports 26 passed.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): serve hosted Raw repositories at /repository/{name}/{path}"
```

---

### Task 11: Compaction, the maintenance runner and real-transaction races

**Files:**
- Modify: `backend/src/megooarti/storage/blobs.py`
- Create: `backend/src/megooarti/maintenance.py`
- Modify: `backend/src/megooarti/main.py` (replace the whole file)
- Test: `backend/tests/storage/test_compaction.py`
- Test: `backend/tests/test_maintenance.py`
- Test: `backend/tests/storage/test_races.py`

**Interfaces:**
- Consumes: `lock_blob`, `referenced` (Task 4); `backend_for`; `RepositoryContext` (Task 9); `Settings.compaction_interval_seconds`, `Settings.blob_grace_seconds`.
- Produces:
  - `megooarti.storage.blobs.compact(sessionmaker, settings, *, now, grace_seconds, temporary_max_age_seconds=86400) -> int` — removes blobs unreferenced for longer than the grace period and sweeps old temporary files; returns how many blobs it removed
  - `megooarti.maintenance.run_exclusively(engine, lock_key, job) -> bool` — runs `job` unless another connection holds the session-level advisory lock; `False` if it was skipped
  - `megooarti.maintenance.run_periodically(name, interval_seconds, job) -> None` — runs forever; a failing job is logged and tried again next time
  - The application starts compaction on `compaction_interval_seconds` (0 disables it), one container at a time.

- [ ] **Step 1: Write the failing tests**

`backend/tests/storage/test_compaction.py`:

```python
import os
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from megooarti.repositories.models import Asset, Repository
from megooarti.storage import blobs
from megooarti.storage.models import Blob

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
DAY = 86400


async def recorded(db, backend, store, stage, content: bytes, unreferenced_for: int | None) -> Blob:
    blob = await blobs.record(db, backend, store.id, await stage(content))
    if unreferenced_for is not None:
        blob.unreferenced_since = NOW - timedelta(seconds=unreferenced_for)
    await db.flush()
    return blob


async def remaining(db) -> set[str]:
    return set(await db.scalars(select(Blob.sha256)))


async def test_only_content_unreferenced_beyond_the_grace_period_is_removed(
    db, sessionmaker, settings, default_store, backend, stage
):
    old = await recorded(db, backend, default_store, stage, b"old", 2 * DAY)
    recent = await recorded(db, backend, default_store, stage, b"recent", 3600)
    unmarked = await recorded(db, backend, default_store, stage, b"unmarked", None)
    await db.commit()

    removed = await blobs.compact(sessionmaker, settings, now=NOW, grace_seconds=DAY)

    assert removed == 1
    assert await remaining(db) == {recent.sha256, unmarked.sha256}
    assert not await backend.exists(old.sha256)
    assert await backend.exists(recent.sha256)


async def test_content_that_is_used_again_is_kept_and_its_mark_cleared(
    db, sessionmaker, settings, default_store, backend, stage
):
    blob = await recorded(db, backend, default_store, stage, b"back in use", 2 * DAY)
    repository = Repository(
        name="files", name_key="files", format="raw", type="hosted", blob_store_id=default_store.id
    )
    db.add(repository)
    await db.flush()
    db.add(
        Asset(
            repository_id=repository.id,
            path="a.bin",
            blob_id=blob.id,
            content_type="application/octet-stream",
            created_by="dana",
        )
    )
    await db.commit()

    removed = await blobs.compact(sessionmaker, settings, now=NOW, grace_seconds=DAY)

    assert removed == 0
    assert await backend.exists(blob.sha256)
    assert await db.scalar(select(Blob.unreferenced_since).where(Blob.id == blob.id)) is None


async def test_old_temporary_files_are_swept(
    db, sessionmaker, settings, default_store, backend, stage
):
    abandoned = await stage(b"never finished")
    in_flight = await stage(b"still arriving")
    two_days_ago = time.time() - 2 * DAY
    os.utime(abandoned.token, (two_days_ago, two_days_ago))

    await blobs.compact(sessionmaker, settings, now=NOW, grace_seconds=DAY)

    assert not os.path.exists(abandoned.token)
    assert os.path.exists(in_flight.token)
```

`backend/tests/test_maintenance.py`:

```python
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.maintenance import run_exclusively, run_periodically

LOCK_KEY = 0x7E57_0001


@pytest.fixture
async def engine(database_url):
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def test_the_job_runs_when_nobody_else_holds_the_lock(engine):
    runs = []

    async def job() -> None:
        runs.append("ran")

    assert await run_exclusively(engine, LOCK_KEY, job) is True
    assert await run_exclusively(engine, LOCK_KEY, job) is True
    assert runs == ["ran", "ran"]


async def test_the_job_is_skipped_while_another_connection_holds_the_lock(engine):
    runs = []

    async def job() -> None:
        runs.append("ran")

    async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as other:
        await other.execute(text(f"SELECT pg_advisory_lock({LOCK_KEY})"))
        skipped = await run_exclusively(engine, LOCK_KEY, job)
        await other.execute(text(f"SELECT pg_advisory_unlock({LOCK_KEY})"))

    assert skipped is False
    assert runs == []


async def test_the_lock_is_released_when_the_job_fails(engine):
    async def failing() -> None:
        raise RuntimeError("the job broke")

    async def fine() -> None:
        return None

    with pytest.raises(RuntimeError):
        await run_exclusively(engine, LOCK_KEY, failing)

    assert await run_exclusively(engine, LOCK_KEY, fine) is True


async def test_a_periodic_job_keeps_running_after_a_failure():
    runs = []

    async def job() -> None:
        runs.append(len(runs))
        if len(runs) == 1:
            raise RuntimeError("the first run broke")

    task = asyncio.create_task(run_periodically("test", 0.01, job))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(runs) >= 3
```

`backend/tests/storage/test_races.py`:

```python
"""Behaviour that only real, concurrent transactions can show.

The other tests share one connection. These are synchronous, migrate their own
database, and drive their own event loop, like the migration tests.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

from alembic import command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.config import Settings
from megooarti.db.schema import alembic_config
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Asset, Repository
from megooarti.storage import blobs
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore
from tests.repositories.conftest import body, someone

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
Factory = async_sessionmaker[AsyncSession]


def run(database_url: str, tmp_path, scenario: Callable[[Factory, Settings], Awaitable[None]]):
    command.upgrade(alembic_config(database_url), "head")
    settings = Settings(_env_file=None, database_url=database_url, data_dir=tmp_path)

    async def main() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            await scenario(async_sessionmaker(engine, expire_on_commit=False), settings)
        finally:
            await engine.dispose()

    asyncio.run(main())


async def create_files(factory: Factory) -> tuple[Repository, BlobStore]:
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="files",
            format="raw",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        store = await db.get(BlobStore, repository.blob_store_id)
        await db.commit()
        return repository, store


def test_compaction_waits_for_an_upload_of_the_same_content(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, store = await create_files(factory)
        backend = backend_for(settings, store)

        async def staged():
            return await backend.stage(body(b"shared content"))

        async with factory() as db:
            blob = await blobs.record(db, backend, store.id, await staged())
            blob.unreferenced_since = NOW - timedelta(days=2)
            await db.commit()

        async with factory() as uploading:
            again = await blobs.record(uploading, backend, store.id, await staged())
            compaction = asyncio.create_task(
                blobs.compact(factory, settings, now=NOW, grace_seconds=3600)
            )
            finished, _ = await asyncio.wait({compaction}, timeout=1)
            assert not finished, "compaction did not wait for the upload being recorded"
            uploading.add(
                Asset(
                    repository_id=repository.id,
                    path="a.bin",
                    blob_id=again.id,
                    content_type="application/octet-stream",
                    created_by="dana",
                )
            )
            await uploading.commit()

        assert await asyncio.wait_for(compaction, timeout=30) == 0
        assert await backend.exists(again.sha256)
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(Blob)) == 1
            assert await db.scalar(select(Blob.unreferenced_since)) is None

    run(empty_database, tmp_path, scenario)


def test_two_writers_of_one_new_path_create_once_and_replace_once(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, store = await create_files(factory)

        async def chunks(data: bytes) -> AsyncIterator[bytes]:
            yield data

        async def write(data: bytes) -> bool:
            async with factory() as db:
                context = RepositoryContext(
                    db=db,
                    settings=settings,
                    repository=await db.get(Repository, repository.id),
                    principal=someone("*"),
                    format=get_format("raw"),
                    backend=backend_for(settings, store),
                )
                _, created = await context.put("same/path.bin", chunks(data))
                await db.commit()
                return created

        results = await asyncio.gather(write(b"first writer"), write(b"second writer"))

        assert sorted(results) == [False, True]
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(Asset)) == 1
            assert await db.scalar(select(func.count()).select_from(Blob)) == 2
            marked = await db.scalar(
                select(func.count()).select_from(Blob).where(Blob.unreferenced_since.is_not(None))
            )
            assert marked == 1

    run(empty_database, tmp_path, scenario)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/storage/test_compaction.py tests/test_maintenance.py tests/storage/test_races.py -q`
Expected: `test_maintenance.py` fails to collect with `No module named 'megooarti.maintenance'`; the compaction tests and `test_compaction_waits_for_an_upload_of_the_same_content` fail with `AttributeError: module 'megooarti.storage.blobs' has no attribute 'compact'`. `test_two_writers_of_one_new_path_create_once_and_replace_once` passes already: it proves the path lock added in Task 9.

- [ ] **Step 3: Implement compaction**

In `backend/src/megooarti/storage/blobs.py`, replace the imports at the top of the file with:

```python
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.config import Settings
from megooarti.repositories.models import Asset
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore
```

and add at the end of the file:

```python
async def compact(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
    grace_seconds: int,
    temporary_max_age_seconds: int = 86400,
) -> int:
    """Remove content nothing has used for the grace period. Returns how many blobs.

    Each blob is handled in its own short transaction, under its lock, and checked
    again there: the mark that selected it is only a hint.
    """
    cutoff = now - timedelta(seconds=grace_seconds)
    async with sessionmaker() as db:
        stores = {store.id: store for store in await db.scalars(select(BlobStore))}
        candidates = (
            await db.execute(
                select(Blob.id, Blob.sha256, Blob.blob_store_id).where(
                    Blob.unreferenced_since <= cutoff
                )
            )
        ).all()

    removed = 0
    for blob_id, sha256, store_id in candidates:
        async with sessionmaker() as db:
            await lock_blob(db, sha256)
            blob = await db.scalar(
                select(Blob).where(
                    Blob.id == blob_id, Blob.unreferenced_since <= cutoff, ~referenced
                )
            )
            if blob is None:
                # In use again, or already gone. Clear a mark that no longer applies.
                await db.execute(
                    update(Blob).where(Blob.id == blob_id, referenced).values(unreferenced_since=None)
                )
                await db.commit()
                continue
            await db.delete(blob)
            await db.flush()
            await backend_for(settings, stores[store_id]).delete(sha256)
            await db.commit()
            removed += 1

    for store in stores.values():
        await backend_for(settings, store).sweep_temporary(temporary_max_age_seconds)
    return removed
```

- [ ] **Step 4: Implement the maintenance runner**

`backend/src/megooarti/maintenance.py`:

```python
"""Background work the application does on a schedule.

Phase 2 replaces this with scheduled tasks an administrator can manage. Until then a
job runs on a fixed interval, in one container at a time.
"""

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger(__name__)

Job = Callable[[], Awaitable[None]]


async def run_exclusively(engine: AsyncEngine, lock_key: int, job: Job) -> bool:
    """Run `job` unless another container is already running it. False if skipped."""
    # A session-level lock lives on this connection, so it is held on a dedicated one
    # in autocommit mode for as long as the job runs.
    async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as connection:
        acquired = await connection.scalar(text(f"SELECT pg_try_advisory_lock({lock_key})"))
        if not acquired:
            return False
        try:
            await job()
        finally:
            await connection.execute(text(f"SELECT pg_advisory_unlock({lock_key})"))
        return True


async def run_periodically(name: str, interval_seconds: float, job: Job) -> None:
    """Run `job` every `interval_seconds`, forever. A failure is logged, not fatal."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await job()
        except Exception:
            log.error("maintenance_failed", job=name, exc_info=True)
```

- [ ] **Step 5: Start compaction with the application**

Replace `backend/src/megooarti/main.py` with:

```python
"""Application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from megooarti import __version__
from megooarti.clock import utcnow
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.errors import ERROR_RESPONSES, UnhandledErrorMiddleware, register_error_handlers
from megooarti.maintenance import run_exclusively, run_periodically
from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
from megooarti.repositories.api import router as repositories_router
from megooarti.repositories.routes import router as content_router
from megooarti.request_id import RequestIdMiddleware
from megooarti.security.api import auth as auth_api
from megooarti.security.api import me as me_api
from megooarti.security.api import roles as roles_api
from megooarti.security.api import users as users_api
from megooarti.security.bootstrap import ensure_initial_admin_password
from megooarti.storage import blobs
from megooarti.storage.api import router as blob_stores_router
from megooarti.system.settings_api import router as settings_router
from megooarti.system.status import router as status_router

log = structlog.get_logger(__name__)

API_PREFIX = "/api/v1"
_FIRST_START_RETRY_SECONDS = 5
# Arbitrary constant, distinct from the other advisory lock keys.
_COMPACTION_LOCK_KEY = 0x4D45474F51


async def _first_start(app: FastAPI) -> None:
    # Read app.state at call time: tests replace the sessionmaker after create_app.
    await ensure_initial_admin_password(
        app.state.sessionmaker, app.state.settings, app.state.head_revision
    )


async def _first_start_when_possible(app: FastAPI, last_error: str) -> None:
    """Keep trying until the database is reachable and migrated."""
    while True:
        await asyncio.sleep(_FIRST_START_RETRY_SECONDS)
        try:
            await _first_start(app)
            return
        except Exception as error:
            if type(error).__name__ != last_error:  # log a change of cause, not every try
                last_error = type(error).__name__
                log.warning("initial_admin_password_deferred", error=last_error)


async def _compact(app: FastAPI) -> None:
    settings = app.state.settings

    async def job() -> None:
        removed = await blobs.compact(
            app.state.sessionmaker,
            settings,
            now=utcnow(),
            grace_seconds=settings.blob_grace_seconds,
        )
        log.info("compaction_finished", removed=removed)

    await run_exclusively(app.state.engine, _COMPACTION_LOCK_KEY, job)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    background: list[asyncio.Task[None]] = []
    try:
        await _first_start(app)
    except Exception as error:  # the database is not reachable or not migrated yet
        cause = type(error).__name__
        log.warning("initial_admin_password_deferred", error=cause)
        background.append(asyncio.create_task(_first_start_when_possible(app, cause)))
    if settings.compaction_interval_seconds > 0:
        background.append(
            asyncio.create_task(
                run_periodically(
                    "compaction", settings.compaction_interval_seconds, lambda: _compact(app)
                )
            )
        )
    yield
    for task in background:
        task.cancel()
    for task in background:
        with suppress(asyncio.CancelledError):
            await task
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MegooArti",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=_lifespan,
        responses=ERROR_RESPONSES,
    )
    app.state.settings = settings
    # Creating the engine opens no connection; the pool connects on first use.
    # hide_parameters keeps bound values (tokens, password hashes) out of error text and logs.
    app.state.engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, hide_parameters=True
    )
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.head_revision = head_revision()
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    app.include_router(auth_api.router, prefix=API_PREFIX)
    app.include_router(me_api.router, prefix=API_PREFIX)
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(roles_api.router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)
    app.include_router(blob_stores_router, prefix=API_PREFIX)
    app.include_router(repositories_router, prefix=API_PREFIX)
    app.include_router(content_router)  # /repository/..., outside the JSON API

    # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
    # first, so its 500 response passes through every other middleware, and keep
    # RequestIdMiddleware last, so everything else runs with a request ID.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/storage/test_compaction.py tests/test_maintenance.py tests/storage/test_races.py -q`
Expected: 9 passed.

Run in `backend/`: `uv run pytest -q`
Expected: no failures.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(storage): compact unreferenced blobs on a schedule, one container at a time"
```

---

### Task 12: Container test and documentation

**Files:**
- Modify: `backend/tests/test_container.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the running stack; the routes from Tasks 5, 7 and 10; the `call` helper and `stack` fixture already in `test_container.py`.
- Produces: a module-scoped `administrator` fixture in `test_container.py` (request headers for the signed-in first-start administrator, after its password change), and a container test that uploads and downloads through the published port with an API token.

- [ ] **Step 1: Write the container test**

In `backend/tests/test_container.py`, add `import hashlib` to the imports, and replace the function `test_the_first_start_administrator_can_sign_in_and_change_the_password` with:

```python
@pytest.fixture(scope="module")
def administrator(stack) -> dict[str, str]:
    """Sign in as the first-start administrator and change the password, once per module.

    Returns the headers that authenticate later requests as that session.
    """
    password = compose("exec", "-T", "backend", "cat", DATA_FILE).stdout.strip()
    assert password

    status, headers, session = call(
        "POST", "/auth/login", {"username": "admin", "password": password}
    )
    assert status == 200
    assert session["must_change_password"] is True
    credentials = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }

    status, _, _ = call(
        "PUT",
        "/me/password",
        {"current_password": password, "new_password": "a brand new password"},
        credentials,
    )
    assert status == 204
    return credentials


@pytest.mark.docker
def test_the_first_start_administrator_can_sign_in_and_change_the_password(administrator):
    status, _, listed = call("GET", "/users", headers=administrator)

    assert status == 200
    assert {user["username"] for user in listed["items"]} == {"admin", "anonymous"}
    still_there = compose("exec", "-T", "backend", "test", "-e", DATA_FILE, check=False)
    assert still_there.returncode != 0


@pytest.mark.docker
def test_a_file_is_uploaded_and_downloaded_with_an_api_token(administrator):
    status, _, created = call("POST", "/me/tokens", {"name": "container-test"}, administrator)
    assert status == 201
    token = {"Authorization": f"Bearer {created['token']}"}
    status, _, _ = call(
        "POST", "/repositories", {"name": "files", "format": "raw", "type": "hosted"}, administrator
    )
    assert status == 201

    content = os.urandom(3 * 1024 * 1024 + 17)
    url = f"http://127.0.0.1:{HTTP_PORT}/repository/files/big/blob.bin"

    upload = urllib.request.Request(url, data=content, method="PUT", headers=token)
    with urllib.request.urlopen(upload, timeout=60) as response:
        assert response.status == 201

    with urllib.request.urlopen(urllib.request.Request(url, headers=token), timeout=60) as response:
        assert response.read() == content
        assert response.headers["X-Checksum-Sha256"] == hashlib.sha256(content).hexdigest()

    part = urllib.request.Request(url, headers={**token, "Range": "bytes=10-19"})
    with urllib.request.urlopen(part, timeout=60) as response:
        assert response.status == 206
        assert response.read() == content[10:20]

    count = "find /var/lib/megooarti/blobs/default/content -type f | wc -l"
    stored = compose("exec", "-T", "backend", "sh", "-c", count)
    assert stored.stdout.strip() == "1"
```

- [ ] **Step 2: Run the container tests**

Run in `backend/`: `uv run pytest -m docker -q`
Expected: 7 passed.

- [ ] **Step 3: Document it**

In `README.md`, add these rows to the table in the **Configuration** section, after the `MEGOOARTI_LOGIN_FAILURE_WINDOW_SECONDS` row:

```markdown
| `MEGOOARTI_COMPACTION_INTERVAL_SECONDS` | `3600` | How often unused blob content is removed; `0` disables it |
| `MEGOOARTI_BLOB_GRACE_SECONDS` | `86400` | How long content is kept after nothing uses it |
```

and add this section before **Health endpoints**:

````markdown
## Repositories

A **blob store** is where file content is kept; the `default` one is a directory under
the data directory. A **repository** holds files in one format. So far there is one
format, `raw` (arbitrary files by path), and one type, `hosted` (files you publish).

Create a repository, then use it with any HTTP client:

```bash
curl -u admin -H 'Content-Type: application/json' \
  -d '{"name":"files","format":"raw","type":"hosted"}' \
  http://localhost:8000/api/v1/repositories

curl -u admin -T ./build/app.tar.gz http://localhost:8000/repository/files/releases/app.tar.gz
curl -u admin -O http://localhost:8000/repository/files/releases/app.tar.gz
```

In place of a password, use an API token as the password, or send it as
`Authorization: Bearer <token>`.

- **Permissions** are `repository:<format>:<name>:<action>`, where the action is `read`,
  `add` (a new path), `edit` (replace a path) or `delete`. For example
  `repository:raw:files:read`, or `repository:raw` for everything on every Raw repository.
- **Deployment policy** per repository: `allow_redeploy` (default), `disable_redeploy`
  (a path can be written once) or `read_only`.
- **Uploads are verified.** If the client sends `Content-Length`, or an
  `X-Checksum-Md5`, `X-Checksum-Sha1` or `X-Checksum-Sha256` header, the received bytes
  must match or nothing is stored. Downloads carry the same checksum headers.
- **Downloads** support `Range`, `If-None-Match` and `If-Modified-Since`.
- **Files always download**; they are never rendered in the browser, because they are
  served from the same site as the administration API.
- **Public content.** With anonymous access on, anyone, signed in or not, may do what
  the `anonymous` user's roles allow on repositories.
- **Identical content is stored once.** Deleting a file frees its content only after
  nothing has used it for `MEGOOARTI_BLOB_GRACE_SECONDS`.
- A repository's name, format, type and blob store cannot be changed after creation.
````

- [ ] **Step 4: Verify the README commands**

Run in the repository root, with the stack from `docker compose up --build --detach --wait` running and `admin` holding a password you know:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{"name":"readme-check","format":"raw","type":"hosted"}' http://localhost:8000/api/v1/repositories
echo "hello" > hello.txt
curl -u admin -T hello.txt http://localhost:8000/repository/readme-check/hello.txt
curl -u admin http://localhost:8000/repository/readme-check/hello.txt
rm hello.txt
```

Expected: the first command prints the repository as JSON; the last prints `hello`. If no stack with a known administrator password is at hand, the container test in Step 2 exercises the same routes; note in the ledger that this manual check was skipped.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add README.md backend
git commit -m "test(container): upload and download through the published port; document repositories"
```
