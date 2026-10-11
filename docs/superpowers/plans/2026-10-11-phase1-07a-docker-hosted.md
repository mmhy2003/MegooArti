# Hosted Docker Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docker login`, `docker push` and `docker pull` work against `repo.example.com/<repository>/<image>:<tag>`, with images for several platforms, tags that can be made immutable, anonymous pull through roles, and disk space that comes back when an image is deleted.

**Architecture:** The registry API is served at `/v2/` by routes of its own, which decide who is asking and answer in the registry's error shape; the first part of an image's name is the repository, and everything after it goes to the Docker format through the same dispatcher as every other format. A container client signs in at `/v2/token` and is given a registry token: a sealed, five-minute statement of who signed in, never stored, checked against the user, the roles and the API token on every request. A layer is a blob stored once for the repository; a manifest is a file that records the blobs and manifests it refers to; a tag is a file holding the manifest it names, so the deployment policy applies to it. Deleting a manifest removes what only it used, and maintenance removes what no manifest ended up using. A layer arrives in chunks over several requests into one file in the blob store's temporary area, which is hashed where it lies when the upload completes.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, Alembic, cryptography (Fernet), pytest + pytest-asyncio, Docker (the daemon and client of the machine, and the `quay.io/skopeo/stable` image, for the real-client tests only).

**Spec:** [docs/superpowers/specs/2026-10-11-docker-format-design.md](../specs/2026-10-11-docker-format-design.md), sections 4.1, 5, 6, 7, 10, 11 and the plan 7a part of 12. Business requirements: [docs/BRD.md](../../BRD.md) FMT-4 (hosted; the registry API, chunked upload, manifest lists, token authentication), FMT-5, FMT-7, SEC-9, NFR-1. Task 7 amends the spec where this plan settles something the spec left open.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | A registry token is `mgr_` followed by a Fernet token that seals `{"for": "registry", "user", "method", "token"}`. Its age is the Fernet token's own timestamp, checked with `decrypt_at_time`. | The key that seals remote credentials already exists. The stated purpose keeps anything else sealed with that key from being taken for a registry token. |
| P2 | A registry token is not accepted at `/v2/token`. | A client that could trade one for the next would never present its password or API token again, and the five minutes of the spec's risk table would have no end. |
| P3 | A request under `/v2/` without an `Authorization` header is answered `401` with the challenge even while anonymous access is on. | A container client sends nothing until it is challenged. It then fetches a token for nobody, which is how it learns that it may read. |
| P4 | A signed-in caller who may not do something gets `403 DENIED`; the anonymous user gets `401` with the challenge. | The client then asks its user to sign in, instead of reporting that access is denied to someone who never said who they are. |
| P5 | What a file refers to is recorded as paths, in `asset_references(asset_id, target)`, not as links between rows. | A reference can then be recorded before what it names has arrived, which a proxy (plan 7b) needs. Deleting the file removes its references with it. |
| P6 | Pushing a manifest, deleting one and the maintenance sweep take one lock per repository, named `references`. | D8: none of them may decide what is still used while another changes it. Manifest pushes to one repository take turns; they are short. |
| P7 | An upload's ID is its row's UUID as 32 hexadecimal digits. Its file is `tmp/upload-chunked-<id>` in the blob store. Its `key` is the image it was begun for, and it can be continued only under that image in that repository. | The ID is the only part of the address a client chooses nothing about, so it is the only thing that becomes part of a file name. |
| P8 | A chunk that stops arriving half-way is taken back: the file is cut to the size it had. Chunks for one upload take turns within a process, and a chunk that states where it starts must start where the upload ends. | A client that resumes asks how much arrived, and must be told the size of whole chunks. |
| P9 | Completing an upload of a blob that is already stored discards the upload. Two completions of one blob take a lock named for its digest. | Two pushes of images that share a layer finish it together as a matter of course. |
| P10 | A format says where it is served (`served_at`). A Docker repository asked for under `/repository/` is `404`, like one that does not exist. | D2. The content route must not become a second way in, with other errors and no challenge. |
| P11 | Formats get a `maintain(context, now)` hook, called for every repository by the existing periodic job before blobs are compacted, with no principal. `context.sweep(path)` removes a file without a permission check, and is for maintenance only. | Nobody is calling, so there is nobody to authorise. Running before compaction starts the wait for the bytes at once. |
| P12 | Pushing a tag with the manifest it already names stores nothing, whatever the deployment policy. Moving a tag where tags cannot be moved is `409 DENIED`. | Docker pushes an image again as a matter of course; that must not fail on a repository whose tags are immutable. |
| P13 | A manifest is stored per image (`manifests/<image>/<digest>`), a blob per repository. A list's platforms must be manifests of the same image. | A manifest is deleted by its address under an image; a layer is shared by design (D6). |
| P14 | A layer that lists external addresses (`urls`) need not be in the repository. A manifest of schema 1 is refused. | Windows base layers are kept elsewhere by design. Docker removed schema 1. |
| P15 | The catalog and a tag list include what has a tag. Their pages are 100 and 1,000 entries by default, at most 1,000 and 10,000. | A tag is the component (D7). An image that lost its last tag is reachable by digest only. |
| P16 | Between this plan and plans 7b and 7c the format offers `hosted` only. | The generic proxy and group engines do not speak the registry's protocol. |
| P17 | The real-client test gives the Docker client a configuration directory of its own, which already names a registry so that `docker login` keeps what it learns there, and the address of the daemon the machine's current context uses. It reads the image's file back out instead of running the image. | The user's sign-ins and credential store are not touched. An image built from nothing has no program to run, and building one needs a base image from the internet. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; settings prefixed `MEGOOARTI_` and listed in `README.md`; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; only the security package reads `Principal.patterns`; every route authenticates through a dependency in `AUTHENTICATION_DEPENDENCIES`; formats do not commit, the route does; a token or password is never logged; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds one migration (`0005`), no setting and no dependency.**
- **Errors under `/v2/` have the registry's shape** (`{"errors": [{"code", "message", "detail"}]}`), with `Docker-Distribution-Api-Version: registry/2.0`. This is the one API that does not use the standard error envelope. An `ApiError` raised by the core is given the code that fits its status.
- **A Docker repository is served only under `/v2/`.**
- **A registry token is never stored and never logged**, and says only who signed in. The user, the roles and the API token are read again on every request.
- **Only `docker/format.py` touches the repository context.** `docker/names.py` and `docker/manifests.py` are pure. `docker/routes.py` decides who is asking and whether they may read, as the content route does.
- **Only SHA-256 digests are taken**, in lower case.
- **Nothing a client chooses becomes part of a file name.** An upload's file is named by its ID, which must be 32 hexadecimal digits.
- **No database connection is held while a chunk arrives or an upload is hashed.**
- **Every change to what a repository's manifests refer to is made under the `references` lock.**
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A registry token after things change.** Its user disabled; the API token behind it revoked; its user's roles changed; anonymous access switched off; five minutes passed; one character altered; something else sealed with the same key; presented at `/v2/token` to get another. None may work, and none may count as a failed sign-in (Task 1).
2. **Requests that arrive together or out of order.** A push and a delete that share a layer; two chunks for one upload; a chunk sent twice; an upload completed twice, or continued under another image or repository, or after it was abandoned (Tasks 3, 6).
3. **What a manifest claims.** A digest in the address that is not its own; layers or platforms that were never pushed, or that belong to another image; a body that is not JSON, is larger than 4 MiB, or is of schema 1; a descriptor without a digest (Tasks 5, 6).
4. **What a delete removes and what it leaves.** A layer two images share; a platform's manifest that has a tag of its own; one manifest under two images; a tag deleted while its image is pinned by digest; a blob nothing ever referred to, before and after a day (Task 6).
5. **Names.** An image whose name contains `manifests`, `blobs`, `tags` or `uploads`; upper case; `..`; a name too long with its repository; a repository of another format under `/v2/`; a Docker repository under `/repository/` (Tasks 4, 5, 6).

---

### Task 1: Security: registry tokens

**Files:**
- Create: `backend/src/megooarti/security/registry_tokens.py`
- Modify: `backend/src/megooarti/secrets_box.py`
- Modify: `backend/src/megooarti/security/tokens.py`
- Modify: `backend/src/megooarti/security/authentication.py`
- Test: `backend/tests/security/test_registry_tokens.py`
- Test: `backend/tests/test_secrets_box.py`

**Interfaces:**
- Consumes: `secrets_box._box`, `authentication.build_principal`, `authentication._anonymous_access`, `authentication.unauthorized`, `users.get_user`, `tokens.touch`, `Credentials` and `client_credentials`.
- Produces:
  - `secrets_box.seal_at(settings, plaintext: str, now: datetime) -> str` and `secrets_box.unseal_within(settings, sealed: str, seconds: int, now: datetime) -> str | None`.
  - `registry_tokens.PREFIX = "mgr_"`, `registry_tokens.LIFETIME_SECONDS = 300`, `registry_tokens.Claims(user_id: uuid.UUID | None, method: str, token_id: uuid.UUID | None = None)`, `registry_tokens.issue(settings, claims, now) -> str`, `registry_tokens.read(settings, value, now) -> Claims | None`.
  - `await tokens.get_token(db, token_id: uuid.UUID, now) -> ApiToken | None`.
  - `Principal.token_id: uuid.UUID | None`: the API token the caller presented.
  - A `Bearer` credential that starts with `mgr_` is read as a registry token by every route.
  - `await authentication.issue_registry_token(request, db, principal: Principal | None) -> str`. Raises `401` if `principal` is None or anonymous while anonymous access is off, and if the request's own credential is a registry token.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_registry_tokens.py`:

```python
import uuid
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti import secrets_box
from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.security import registry_tokens, roles, users
from megooarti.security.authentication import (
    Credentials,
    Principal,
    client_credentials,
    issue_registry_token,
    require,
)
from megooarti.security.models import ApiToken, LoginFailure
from megooarti.security.registry_tokens import Claims
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code

READ = "/_test/maven-read"
ADMIN = "/_test/users-read"
SIGN_IN = "/_test/registry-token"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    def who(principal: Principal) -> dict:
        return {"user": principal.user.username, "method": principal.method}

    @router.get("/maven-read")
    async def maven_read(
        principal: Principal = Depends(require("repository:maven:releases:read")),
    ) -> dict:
        return who(principal)

    @router.get("/users-read")
    async def users_read(principal: Principal = Depends(require("admin:users:read"))) -> dict:
        return who(principal)

    @router.get("/registry-token")
    async def registry_token(
        request: Request,
        credentials: Credentials = Depends(client_credentials),
        db: AsyncSession = Depends(get_session),
    ) -> dict:
        signed_in = "Authorization" in request.headers
        principal = await credentials.principal() if signed_in else None
        return {"token": await issue_registry_token(request, db, principal)}

    app.include_router(router)
    return app


async def sign_in(client, headers: dict | None = None) -> str:
    response = await client.get(SIGN_IN, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def let_anyone_read(db, *permissions: str) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    anonymous = await users.get_user_by_username(db, "anonymous")
    if permissions:
        await roles.create_role(db, "public", "", list(permissions), [])
        await users.set_roles(db, anonymous, ["public"])
    await db.commit()


def test_a_token_states_who_signed_in(settings):
    now = utcnow()
    claims = Claims(uuid.uuid4(), "token", uuid.uuid4())

    value = registry_tokens.issue(settings, claims, now)

    assert value.startswith("mgr_")
    assert registry_tokens.read(settings, value, now) == claims
    assert registry_tokens.read(settings, value, now + timedelta(seconds=299)) == claims
    nobody = registry_tokens.issue(settings, Claims(None, "anonymous"), now)
    assert registry_tokens.read(settings, nobody, now) == Claims(None, "anonymous")


def test_a_token_is_read_only_within_its_lifetime(settings):
    now = utcnow()
    value = registry_tokens.issue(settings, Claims(uuid.uuid4(), "password"), now)

    assert registry_tokens.read(settings, value, now + timedelta(seconds=301)) is None
    assert registry_tokens.read(settings, value, now - timedelta(hours=1)) is None  # not yet made


def test_what_is_not_a_registry_token_is_not_read(settings):
    now = utcnow()
    value = registry_tokens.issue(settings, Claims(uuid.uuid4(), "password"), now)
    altered = value[:-6] + ("AAAAAA" if not value.endswith("AAAAAA") else "BBBBBB")
    # Something else sealed with the same key, such as a remote's password.
    other = "mgr_" + secrets_box.seal_at(settings, "s3cret", now)
    wrong_purpose = "mgr_" + secrets_box.seal_at(
        settings, '{"for": "something", "user": null, "method": "anonymous", "token": null}', now
    )
    odd = "mgr_" + secrets_box.seal_at(
        settings, '{"for": "registry", "user": 7, "method": "password", "token": null}', now
    )

    for candidate in (altered, other, wrong_purpose, odd, "mgr_", "mgr_not-sealed", value[4:], ""):
        assert registry_tokens.read(settings, candidate, now) is None, candidate


async def test_signing_in_with_a_password_gives_a_token_that_works(client, make_user):
    await make_user("root", roles=["admin"])

    token = await sign_in(client, basic("root", PASSWORD))
    response = await client.get(ADMIN, headers=bearer(token))

    assert response.json() == {"user": "root", "method": "password"}


async def test_signing_in_with_an_api_token_keeps_its_limits(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    narrow = await make_token(root, scopes=["repository:maven"])

    token = await sign_in(client, basic("__token__", narrow))
    allowed = await client.get(READ, headers=bearer(token))
    beyond = await client.get(ADMIN, headers=bearer(token))

    assert allowed.json() == {"user": "root", "method": "token"}
    assert (beyond.status_code, error_code(beyond)) == (403, "forbidden")


async def test_wrong_credentials_get_no_token_and_are_counted(client, make_user, db):
    await make_user("root", roles=["admin"])

    response = await client.get(SIGN_IN, headers=basic("root", "not the password"))

    assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'
    assert await db.scalar(select(LoginFailure.count).where(LoginFailure.subject == "user:root"))


async def test_a_token_stops_working_when_its_user_is_disabled(client, make_user, db):
    await make_user("root", roles=["admin"])
    token = await sign_in(client, basic("root", PASSWORD))
    user = await users.get_user_by_username(db, "root")
    await users.update_user(db, user, {"status": "disabled"})
    await db.commit()

    response = await client.get(ADMIN, headers=bearer(token))

    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_a_token_stops_working_when_the_api_token_behind_it_is_revoked(
    client, make_user, make_token, db
):
    root = await make_user("root", roles=["admin"])
    token = await sign_in(client, basic("root", await make_token(root)))
    before = await client.get(ADMIN, headers=bearer(token))
    await db.execute(delete(ApiToken))
    await db.commit()

    after = await client.get(ADMIN, headers=bearer(token))

    assert (before.status_code, after.status_code) == (200, 401)


async def test_a_token_follows_its_users_roles_as_they_are_now(client, make_user, db):
    await make_user("dana")
    token = await sign_in(client, basic("dana", PASSWORD))
    before = await client.get(ADMIN, headers=bearer(token))
    user = await users.get_user_by_username(db, "dana")
    await users.set_roles(db, user, ["admin"])
    await db.commit()

    after = await client.get(ADMIN, headers=bearer(token))

    assert (before.status_code, after.status_code) == (403, 200)


async def test_an_expired_or_altered_token_is_refused_without_being_counted(
    client, make_user, settings, db
):
    root = await make_user("root", roles=["admin"])
    old = registry_tokens.issue(
        settings, Claims(root.id, "password"), utcnow() - timedelta(seconds=301)
    )
    good = await sign_in(client, basic("root", PASSWORD))

    for value in (old, good[:-4] + "AAAA", "mgr_anything"):
        response = await client.get(ADMIN, headers=bearer(value))
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert list(await db.scalars(select(LoginFailure.subject))) == []


async def test_a_token_that_states_something_impossible_is_refused(client, make_user, settings):
    root = await make_user("root", roles=["admin"])
    now = utcnow()
    impossible = [
        Claims(uuid.uuid4(), "password"),  # nobody has this ID
        Claims(root.id, "token"),  # by a token, but which?
        Claims(root.id, "token", uuid.uuid4()),  # a token that does not exist
        Claims(root.id, "anonymous"),
    ]

    for claims in impossible:
        value = registry_tokens.issue(settings, claims, now)
        response = await client.get(ADMIN, headers=bearer(value))
        assert response.status_code == 401, claims


async def test_without_credentials_there_is_no_token_unless_anyone_may_read(client, db):
    refused = await client.get(SIGN_IN)
    await let_anyone_read(db, "repository:maven:releases:read")

    token = await sign_in(client)
    reading = await client.get(READ, headers=bearer(token))
    administering = await client.get(ADMIN, headers=bearer(token))

    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")
    assert reading.json() == {"user": "anonymous", "method": "anonymous"}
    assert administering.status_code == 401  # nobody administers anonymously


async def test_a_token_for_nobody_stops_working_when_anonymous_access_is_switched_off(client, db):
    await let_anyone_read(db, "repository:maven:releases:read")
    token = await sign_in(client)
    await set_setting(db, "anonymous_access", {"enabled": False})
    await db.commit()

    response = await client.get(READ, headers=bearer(token))

    assert response.status_code == 401


async def test_a_registry_token_cannot_be_exchanged_for_another(client, make_user, db):
    # Whoever held one could otherwise keep it alive for ever, past a change of password.
    await make_user("root", roles=["admin"])
    held = await sign_in(client, basic("root", PASSWORD))
    await let_anyone_read(db)
    nobodys = await sign_in(client)

    for value in (held, nobodys):
        response = await client.get(SIGN_IN, headers=bearer(value))
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert (await client.get(ADMIN, headers=bearer(held))).json()["user"] == "root"
```

In `backend/tests/test_secrets_box.py`:

Replace

```python
import os
import time

import pytest
```

with

```python
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
```

Add to the end of `backend/tests/test_secrets_box.py`:

```python
def test_text_sealed_with_the_time_is_read_only_for_so_long(tmp_path):
    settings = settings_in(tmp_path)
    now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)

    sealed = secrets_box.seal_at(settings, SECRET, now)

    assert SECRET not in sealed
    assert secrets_box.unseal_within(settings, sealed, 300, now) == SECRET
    assert secrets_box.unseal_within(settings, sealed, 300, now + timedelta(seconds=300)) == SECRET
    assert secrets_box.unseal_within(settings, sealed, 300, now + timedelta(seconds=301)) is None
    assert secrets_box.unseal_within(settings, sealed, 300, now - timedelta(hours=1)) is None


def test_what_was_not_sealed_here_is_not_read(tmp_path):
    settings = settings_in(tmp_path)
    now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    sealed = secrets_box.seal_at(settings, SECRET, now)
    elsewhere = secrets_box.seal_at(settings_in(tmp_path, secret_key="another key"), SECRET, now)

    for candidate in (sealed[:-3] + "abc", elsewhere, "", "not sealed", "ünïcode"):
        assert secrets_box.unseal_within(settings, candidate, 300, now) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/security/test_registry_tokens.py tests/test_secrets_box.py -q`
Expected: collection error, `cannot import name 'registry_tokens' from 'megooarti.security'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/security/registry_tokens.py`:

```python
"""Registry tokens: what a container client is given at sign-in and sends with requests.

A registry token is not stored anywhere. It is a sealed statement of who signed in and
how, valid for a few minutes. Reading one back gives that statement and nothing more:
the caller loads the user, the roles and the API token again on every request, so a
disabled user or a revoked token is refused at once.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from megooarti import secrets_box
from megooarti.config import Settings

PREFIX = "mgr_"
LIFETIME_SECONDS = 300
# What the sealed text says it is, so that nothing else sealed with the same key can be
# taken for a registry token.
_PURPOSE = "registry"
_METHODS = ("password", "token", "anonymous")


@dataclass(frozen=True)
class Claims:
    """Who signed in. `user_id` is None when nobody did: the anonymous user is meant."""

    user_id: uuid.UUID | None
    method: str
    token_id: uuid.UUID | None = None  # the API token that was presented, if one was


def issue(settings: Settings, claims: Claims, now: datetime) -> str:
    stated = {
        "for": _PURPOSE,
        "user": None if claims.user_id is None else str(claims.user_id),
        "method": claims.method,
        "token": None if claims.token_id is None else str(claims.token_id),
    }
    return PREFIX + secrets_box.seal_at(settings, json.dumps(stated), now)


def read(settings: Settings, value: str, now: datetime) -> Claims | None:
    """What a registry token states, or None if it is not one, was altered or has expired."""
    if not value.startswith(PREFIX):
        return None
    sealed = value.removeprefix(PREFIX)
    text = secrets_box.unseal_within(settings, sealed, LIFETIME_SECONDS, now)
    if text is None:
        return None
    try:
        stated = json.loads(text)
        if stated["for"] != _PURPOSE or stated["method"] not in _METHODS:
            return None
        user, token = stated["user"], stated["token"]
        return Claims(
            user_id=None if user is None else uuid.UUID(user),
            method=stated["method"],
            token_id=None if token is None else uuid.UUID(token),
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
```

In `backend/src/megooarti/secrets_box.py`:

Replace

```python
from contextlib import suppress
from functools import lru_cache
```

with

```python
from contextlib import suppress
from datetime import datetime
from functools import lru_cache
```

Before

```python
def forget_keys() -> None:
```

add

```python
def seal_at(settings: Settings, plaintext: str, now: datetime) -> str:
    """Seal text together with the time, for `unseal_within`. Not for stored secrets."""
    return _box(settings).encrypt_at_time(plaintext.encode(), int(now.timestamp())).decode()


def unseal_within(settings: Settings, sealed: str, seconds: int, now: datetime) -> str | None:
    """What `seal_at` sealed, if that was no more than `seconds` ago. Otherwise None."""
    try:
        opened = _box(settings).decrypt_at_time(sealed.encode(), seconds, int(now.timestamp()))
    except (InvalidToken, ValueError):  # altered, sealed with another key, or not text
        return None
    return opened.decode()
```

In `backend/src/megooarti/security/tokens.py`:

Before

```python
def touch(token: ApiToken, now: datetime) -> None:
```

add

```python
async def get_token(db: AsyncSession, token_id: uuid.UUID, now: datetime) -> ApiToken | None:
    """A token by its ID, if it still exists and has not expired."""
    token = await db.get(ApiToken, token_id)
    if token is None or (token.expires_at is not None and token.expires_at <= now):
        return None
    return token
```

In `backend/src/megooarti/security/authentication.py`:

After

```python
import asyncio
import base64
import secrets
```

add

```python
import uuid
```

Replace

```python
from megooarti.security import sessions, throttle, tokens, users
```

with

```python
from megooarti.security import registry_tokens, sessions, throttle, tokens, users
```

Replace

```python
    public: frozenset[str] = frozenset()

    @property
    def is_anonymous(self) -> bool:
```

with

```python
    public: frozenset[str] = frozenset()
    # The API token the caller presented, if any: what a registry token is issued for.
    token_id: uuid.UUID | None = None

    @property
    def is_anonymous(self) -> bool:
```

Replace

```python
    scopes = None if token is None or token.scopes is None else frozenset(token.scopes)
    return Principal(user, method, await users.user_patterns(db, user), scopes, session, public)
```

with

```python
    scopes = None if token is None or token.scopes is None else frozenset(token.scopes)
    return Principal(
        user,
        method,
        await users.user_patterns(db, user),
        scopes,
        session,
        public,
        None if token is None else token.id,
    )
```

Replace

```python
    scheme = scheme.lower()
    if scheme == "bearer":
        user, token = await _authenticate_token(db, request, credentials.strip())
```

with

```python
    scheme = scheme.lower()
    if scheme == "bearer" and credentials.strip().startswith(registry_tokens.PREFIX):
        return await _from_registry_token(db, request, credentials.strip())
    if scheme == "bearer":
        user, token = await _authenticate_token(db, request, credentials.strip())
```

Before

```python
async def resolve_principal(request: Request, db: AsyncSession) -> Principal | None:
```

add

```python
async def _from_registry_token(db: AsyncSession, request: Request, value: str) -> Principal:
    """Who a registry token stands for, as things are now.

    The token only says who signed in. The user, the roles and the API token are read
    again here, so one that was disabled or revoked since is refused. A token that
    has expired is not a failed attempt: clients fetch a new one as a matter of course.
    """
    now = utcnow()
    refused = unauthorized("The registry token is not valid or has expired.")
    claims = registry_tokens.read(request.app.state.settings, value, now)
    if claims is None:
        raise refused
    if claims.user_id is None:
        anonymous = await _anonymous_access(db)
        if anonymous is None:
            raise refused
        user, patterns = anonymous
        return Principal(user, "anonymous", patterns, public=patterns)
    user = await users.get_user(db, claims.user_id)
    if user is None or user.status != "active" or claims.method == "anonymous":
        raise refused
    if (claims.method == "token") != (claims.token_id is not None):
        raise refused
    token = None
    if claims.token_id is not None:
        token = await tokens.get_token(db, claims.token_id, now)
        if token is None or token.user_id != user.id:
            raise refused
        tokens.touch(token, now)
    return await build_principal(db, user, claims.method, token=token)


async def issue_registry_token(
    request: Request, db: AsyncSession, principal: Principal | None
) -> str:
    """A registry token for whoever is calling: a container client's sign-in.

    `principal` is who the request's credentials identify, or None if it carries
    none. Then the token is the anonymous user's, and is given only while anonymous
    access is on. A registry token is not a credential here: a client that could trade
    one for the next would never have to present its password or API token again.
    """
    scheme, _, presented = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and presented.strip().startswith(registry_tokens.PREFIX):
        raise unauthorized("Sign in with a password or an API token.", scheme="Basic")
    if principal is None or principal.is_anonymous:
        if await _anonymous_access(db) is None:
            raise unauthorized(scheme="Basic")
        claims = registry_tokens.Claims(None, "anonymous")
    else:
        method = "token" if principal.token_id is not None else "password"
        claims = registry_tokens.Claims(principal.user.id, method, principal.token_id)
    return registry_tokens.issue(request.app.state.settings, claims, utcnow())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/security tests/test_secrets_box.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/secrets_box.py backend/src/megooarti/security backend/tests/security/test_registry_tokens.py backend/tests/test_secrets_box.py
git commit -m "feat(security): registry tokens, a sealed statement of who signed in"
```

---

### Task 2: Core: what a file refers to

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0005_add_references_and_uploads.py`
- Modify: `backend/src/megooarti/repositories/models.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Test: `backend/tests/repositories/test_content_references.py`

**Interfaces:**
- Consumes: `RepositoryContext._lock`, `RepositoryContext._record`, `RepositoryContext.delete`, `normalise_path`.
- Produces:
  - Tables `asset_references(asset_id, target)` and `uploads(id, repository_id, key, created_by, created_at, updated_at)`; models `AssetReference` and `Upload`. The `uploads` table is used by Task 3.
  - `await context.lock(name: str) -> None`: until the transaction ends.
  - `await context.present(paths: Collection[str]) -> set[str]`.
  - `await context.references(path: str) -> list[str]`.
  - `await context.referenced(paths: Collection[str]) -> set[str]`.
  - `await context.unreferenced(prefix: str, *, before: datetime, limit: int) -> list[str]`.
  - `await context.store(..., references: Collection[str] | None = None)`: `None` leaves what was recorded alone.
  - `await context.sweep(path: str) -> bool`: removes a file with no permission check. For maintenance only.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_references.py`:

```python
import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Asset, AssetReference
from megooarti.storage.models import Blob
from tests.repositories.conftest import someone
from tests.storage.test_races import Factory, run

EVERYTHING = someone("repository:raw:files")


@pytest.fixture
async def context(files, context_for):
    return await context_for(files, EVERYTHING)


async def store(context, path: str, content: bytes = b"x", **options):
    staged = await context.stage_bytes(content)
    return await context.store(path, staged, **options)


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def make_old(db, *paths: str) -> None:
    long_ago = utcnow() - timedelta(days=3)
    await db.execute(update(Asset).where(Asset.path.in_(paths)).values(updated_at=long_ago))


async def test_a_file_records_what_it_refers_to(context):
    await store(context, "layers/a")
    await store(context, "layers/b")
    await store(context, "images/one", references=["layers/b", "layers/a", "layers/a"])

    assert await context.references("images/one") == ["layers/a", "layers/b"]
    assert await context.references("layers/a") == []
    assert await context.references("nothing/here") == []


async def test_storing_again_replaces_what_was_recorded_unless_nothing_is_said(context):
    await store(context, "images/one", references=["layers/a", "layers/b"])

    await store(context, "images/one", b"again")
    kept = await context.references("images/one")
    await store(context, "images/one", b"third", references=["layers/c"])
    replaced = await context.references("images/one")
    await store(context, "images/one", b"fourth", references=[])

    assert (kept, replaced) == (["layers/a", "layers/b"], ["layers/c"])
    assert await context.references("images/one") == []


async def test_which_paths_are_still_referred_to(context):
    await store(context, "images/one", references=["layers/a", "layers/b"])
    await store(context, "images/two", references=["layers/b", "layers/c"])

    asked = ["layers/a", "layers/b", "layers/c", "layers/d"]
    before = await context.referenced(asked)
    await context.delete("images/one")
    after = await context.referenced(asked)

    assert before == {"layers/a", "layers/b", "layers/c"}
    assert after == {"layers/b", "layers/c"}  # deleting a file forgets what it referred to
    assert await context.referenced([]) == set()


async def test_which_paths_have_a_file(context):
    await store(context, "layers/a")
    await store(context, "layers/b")

    assert await context.present(["layers/a", "layers/b", "layers/c"]) == {"layers/a", "layers/b"}
    assert await context.present([]) == set()


async def test_references_are_those_of_one_repository(context, context_for, db):
    other = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    elsewhere = await context_for(other, someone("repository:raw:more"))
    await store(context, "layers/a")
    await store(elsewhere, "images/one", references=["layers/a"])

    assert await context.referenced(["layers/a"]) == set()
    assert await elsewhere.referenced(["layers/a"]) == {"layers/a"}
    assert await context.references("images/one") == []
    assert await elsewhere.present(["layers/a"]) == set()


async def test_what_nothing_refers_to_can_be_found_once_it_is_old(context, db):
    for path in ("layers/used", "layers/unused", "layers/new", "layers/100%_odd", "other/unused"):
        await store(context, path)
    await store(context, "images/one", references=["layers/used"])
    await make_old(db, "layers/used", "layers/unused", "layers/100%_odd", "other/unused")
    a_day_ago = utcnow() - timedelta(days=1)

    found = await context.unreferenced("layers/", before=a_day_ago, limit=10)
    one = await context.unreferenced("layers/", before=a_day_ago, limit=1)
    literal = await context.unreferenced("layers/100%_", before=a_day_ago, limit=10)
    wildcard = await context.unreferenced("layers/1__%", before=a_day_ago, limit=10)

    assert found == ["layers/100%_odd", "layers/unused"]
    assert one == ["layers/100%_odd"]
    assert (literal, wildcard) == (["layers/100%_odd"], [])  # the prefix is taken literally


async def test_maintenance_removes_a_file_without_asking_who(files, context_for, db):
    writer = await context_for(files, EVERYTHING)
    await store(writer, "layers/a", b"content")
    nobody = await context_for(files, None)

    with pytest.raises(ApiError) as refused:
        await nobody.delete("layers/a")
    removed = await nobody.sweep("layers/a")
    again = await nobody.sweep("layers/a")

    assert refused.value.status_code == 401
    assert (removed, again) == (True, False)
    assert await count(db, Asset) == 0
    assert await db.scalar(select(Blob.unreferenced_since)) is not None  # left for compaction


async def test_sweeping_a_read_only_repository_still_works(db, context_for):
    frozen = await service.create_repository(
        db, name="frozen", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    writer = await context_for(frozen, someone("repository:raw:frozen"))
    await store(writer, "layers/a")
    await service.update_repository(
        db, frozen, online=True, hosted={"deployment_policy": "read_only"}
    )
    await db.commit()

    assert await (await context_for(frozen, None)).sweep("layers/a") is True


async def test_deleting_a_file_removes_its_references_with_it(context, db):
    await store(context, "images/one", references=["layers/a", "layers/b"])

    await context.delete("images/one")

    assert await count(db, AssetReference) == 0


def test_a_named_lock_makes_two_transactions_take_turns(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        async with factory() as db:
            repository = await service.create_repository(
                db, name="files", format="raw", type="hosted", online=True, blob_store="default"
            )
            await db.commit()
        order = []

        async def work(name: str, pause: float) -> None:
            async with factory() as db:
                context = await build_context(db, settings, repository, EVERYTHING)
                await context.lock("references")
                order.append(f"{name} in")
                await asyncio.sleep(pause)
                order.append(f"{name} out")
                await db.commit()

        first = asyncio.create_task(work("first", 0.3))
        await asyncio.sleep(0.1)
        await work("second", 0)
        await first

        assert order == ["first in", "first out", "second in", "second out"]

    run(empty_database, tmp_path, scenario)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_references.py -q`
Expected: collection error, `cannot import name 'AssetReference' from 'megooarti.repositories.models'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/migrations/versions/0005_add_references_and_uploads.py`:

```python
"""add asset references and uploads in progress

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_references",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(length=1024), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_asset_references_asset_id_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("asset_id", "target", name=op.f("pk_asset_references")),
    )
    op.create_index(
        op.f("ix_asset_references_target"), "asset_references", ["target"], unique=False
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=1024), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_uploads_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )


def downgrade() -> None:
    op.drop_table("uploads")
    op.drop_index(op.f("ix_asset_references_target"), table_name="asset_references")
    op.drop_table("asset_references")
```

In `backend/src/megooarti/repositories/models.py`:

Before

```python
class RepositoryMember(Base):
```

add

```python
class AssetReference(Base):
    """A file refers to another file of its repository, by path.

    For formats in which one file is only usable with others: a container image's
    manifest refers to its layers. A file nothing refers to can be told apart.
    """

    __tablename__ = "asset_references"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    target: Mapped[str] = mapped_column(String(1024), primary_key=True, index=True)


class Upload(Base):
    """An upload that arrives over several requests. Its bytes are with the blob store."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    # What it is an upload for, in the format's own terms.
    key: Mapped[str] = mapped_column(String(1024))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

In `backend/src/megooarti/repositories/content.py`:

Replace

```python
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
```

with

```python
from sqlalchemy import delete, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
```

Replace

```python
from megooarti.repositories.models import Asset, Component, Repository
```

with

```python
from megooarti.repositories.models import Asset, AssetReference, Component, Repository
```

Before

```python
    async def get(self, path: str, *, fresh: bool = False) -> Asset | None:
```

add

```python
    async def lock(self, name: str) -> None:
        """Serialise work on something a format names, until this transaction ends.

        For a change that is only right if nothing else of its kind happens meanwhile,
        such as deciding that a file is no longer referred to and removing it.
        """
        await self._lock("format", name)
```

Before

```python
    async def versions(self, namespace: str, name: str) -> dict[str, datetime]:
```

add

```python
    async def present(self, paths: Collection[str]) -> set[str]:
        """Which of these paths have a file."""
        if not paths:
            return set()
        rows = await self.db.scalars(
            select(Asset.path).where(
                Asset.repository_id == self.repository.id, Asset.path.in_(paths)
            )
        )
        return set(rows)

    async def references(self, path: str) -> list[str]:
        """The paths the file at `path` refers to, in order."""
        rows = await self.db.scalars(
            select(AssetReference.target)
            .join(Asset, Asset.id == AssetReference.asset_id)
            .where(Asset.repository_id == self.repository.id, Asset.path == path)
            .order_by(AssetReference.target)
        )
        return list(rows)

    async def referenced(self, paths: Collection[str]) -> set[str]:
        """Which of these paths some file in this repository refers to."""
        if not paths:
            return set()
        rows = await self.db.scalars(
            select(AssetReference.target)
            .join(Asset, Asset.id == AssetReference.asset_id)
            .where(Asset.repository_id == self.repository.id, AssetReference.target.in_(paths))
            .distinct()
        )
        return set(rows)

    async def unreferenced(self, prefix: str, *, before: datetime, limit: int) -> list[str]:
        """Files under `prefix` that nothing refers to and that have not changed since `before`.

        For maintenance: what a format stored for the sake of other files, and no file
        ended up using.
        """
        referrer = aliased(Asset)
        used = (
            select(AssetReference.asset_id)
            .join(referrer, referrer.id == AssetReference.asset_id)
            .where(
                referrer.repository_id == self.repository.id,
                AssetReference.target == Asset.path,
            )
            .exists()
        )
        rows = await self.db.scalars(
            select(Asset.path)
            .where(
                Asset.repository_id == self.repository.id,
                Asset.path.startswith(prefix, autoescape=True),
                Asset.updated_at < before,
                ~used,
            )
            .order_by(Asset.path)
            .limit(limit)
        )
        return list(rows)
```

Replace

```python
        kind: str = "asset",
        attributes: dict[str, Any] | None = None,
        component_attributes: dict[str, Any] | None = None,
    ) -> tuple[Asset, bool]:
        """Record staged content at a path, in the caller's transaction.

        Checks permission and policy under the path lock. Never commits: the caller
        does, and a rollback undoes everything recorded here. `attributes`, when given,
        become what is recorded about the file itself, and `component_attributes` the
        attributes of the component it belongs to.
        """
        return await self._record(
            path,
            staged,
            content_type=content_type,
            kind=kind,
            checked=True,
            attributes=attributes,
            component_attributes=component_attributes,
        )
```

with

```python
        kind: str = "asset",
        attributes: dict[str, Any] | None = None,
        component_attributes: dict[str, Any] | None = None,
        references: Collection[str] | None = None,
    ) -> tuple[Asset, bool]:
        """Record staged content at a path, in the caller's transaction.

        Checks permission and policy under the path lock. Never commits: the caller
        does, and a rollback undoes everything recorded here. `attributes`, when given,
        become what is recorded about the file itself, and `component_attributes` the
        attributes of the component it belongs to. `references`, when given, are the
        paths of the files in this repository that this one refers to, replacing any
        recorded before.
        """
        asset, created = await self._record(
            path,
            staged,
            content_type=content_type,
            kind=kind,
            checked=True,
            attributes=attributes,
            component_attributes=component_attributes,
        )
        if references is not None:
            await self.db.execute(delete(AssetReference).where(AssetReference.asset_id == asset.id))
            targets = sorted(set(references))
            if targets:
                await self.db.execute(
                    insert(AssetReference),
                    [{"asset_id": asset.id, "target": target} for target in targets],
                )
        return asset, created
```

Replace

```python
    async def delete(self, path: str) -> bool:
        """Remove what is at a path. False if there was nothing. The caller commits."""
        path = normalise_path(path)
        authorize(self.principal, self.permission("delete"), scheme="Basic")
        self._check_policy(replacing=False)
        await self._lock("path", path)
```

with

```python
    async def delete(self, path: str) -> bool:
        """Remove what is at a path. False if there was nothing. The caller commits."""
        path = normalise_path(path)
        authorize(self.principal, self.permission("delete"), scheme="Basic")
        self._check_policy(replacing=False)
        return await self._remove(path)

    async def sweep(self, path: str) -> bool:
        """Remove what is at a path as maintenance does. False if there was nothing.

        Nobody asked for this, so no permission is checked and a read-only repository
        does not stop it. Never call it for a request.
        """
        return await self._remove(normalise_path(path))

    async def _remove(self, path: str) -> bool:
        await self._lock("path", path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_content_references.py tests/test_migrations.py -q`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/migrations backend/src/megooarti/repositories backend/tests/repositories/test_content_references.py
git commit -m "feat(repositories): record what a file refers to, and find what nothing refers to"
```

---

### Task 3: Core: uploads in progress

**Files:**
- Create: `backend/src/megooarti/repositories/uploads.py`
- Modify: `backend/src/megooarti/storage/backends.py`
- Test: `backend/tests/repositories/test_uploads.py`
- Test: `backend/tests/storage/test_backends.py`

**Interfaces:**
- Consumes: the `Upload` model (Task 2); `context.require_write`, `context.release`, `context.backend`, `context.discard`; `StagedBlob`; `KeyedLocks`; `backend_for`.
- Produces:
  - On a blob store's backend: `await create_upload(upload: str)`, `await upload_size(upload: str) -> int | None`, `await append(upload: str, chunks: AsyncIterator[bytes]) -> int` (the size after; cut back to the size before if the chunks fail), `await adopt(upload: str) -> StagedBlob` (hashed where it lies), `await abandon(upload: str)`.
  - `uploads.UnknownUpload`, `uploads.OutOfOrder(size)`, `uploads.Progress(id: str, size: int)`.
  - `await uploads.begin(context, key: str) -> str`.
  - `await uploads.progress(context, upload_id: str, key: str) -> Progress`.
  - `await uploads.append(context, upload_id, key, chunks, *, at: int | None = None) -> int`.
  - `await uploads.complete(context, upload_id, key) -> StagedBlob`: the caller stores or discards it.
  - `await uploads.abandon(context, upload_id, key) -> None`.
  - `await uploads.sweep(sessionmaker, settings, *, now, max_age_seconds) -> int`.
  - Each of the first five needs `add` or `edit`, and raises `UnknownUpload` for an ID that is not 32 hexadecimal digits, is not of this repository, or was begun for another `key`.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/tests/storage/test_backends.py`:

```python
UPLOAD = "0123456789abcdef0123456789abcdef"


async def test_an_upload_grows_by_whole_appends(backend):
    before = await backend.upload_size(UPLOAD)
    await backend.create_upload(UPLOAD)

    empty = await backend.upload_size(UPLOAD)
    first = await backend.append(UPLOAD, pieces(BODY[:5000]))
    second = await backend.append(UPLOAD, pieces(BODY[5000:]))
    nothing = await backend.append(UPLOAD, pieces(b""))

    assert (before, empty, first, second, nothing) == (None, 0, 5000, len(BODY), len(BODY))
    assert await backend.upload_size(UPLOAD) == len(BODY)


async def test_an_append_that_stops_arriving_is_taken_back(backend):
    async def interrupted() -> AsyncIterator[bytes]:
        yield BODY[5000:8000]
        raise ConnectionError("the client went away")

    await backend.create_upload(UPLOAD)
    await backend.append(UPLOAD, pieces(BODY[:5000]))

    with pytest.raises(ConnectionError):
        await backend.append(UPLOAD, interrupted())
    resumed = await backend.append(UPLOAD, pieces(BODY[5000:]))

    assert resumed == len(BODY)
    assert (await backend.adopt(UPLOAD)).sha256 == hashlib.sha256(BODY).hexdigest()


async def test_a_finished_upload_becomes_staged_content_without_a_copy(backend, tmp_path):
    await backend.create_upload(UPLOAD)
    await backend.append(UPLOAD, pieces(BODY))
    (only,) = temporary_files(tmp_path / "store")

    staged = await backend.adopt(UPLOAD)

    assert staged.size == len(BODY)
    assert staged.sha256 == hashlib.sha256(BODY).hexdigest()
    assert staged.md5 == hashlib.md5(BODY).hexdigest()
    assert staged.sha1 == hashlib.sha1(BODY).hexdigest()
    assert staged.sha512 == hashlib.sha512(BODY).hexdigest()
    assert staged.token == str(only)  # the same file, not another one
    await backend.commit(staged)
    assert await read(backend, staged.sha256) == BODY
    assert temporary_files(tmp_path / "store") == []
    assert await backend.upload_size(UPLOAD) is None


async def test_an_abandoned_upload_is_gone_and_abandoning_twice_is_harmless(backend, tmp_path):
    await backend.create_upload(UPLOAD)
    await backend.append(UPLOAD, pieces(BODY))

    await backend.abandon(UPLOAD)
    await backend.abandon(UPLOAD)

    assert await backend.upload_size(UPLOAD) is None
    assert temporary_files(tmp_path / "store") == []
    with pytest.raises(FileNotFoundError):
        await backend.append(UPLOAD, pieces(BODY))


async def test_an_upload_nobody_adds_to_is_swept_like_anything_temporary(backend, tmp_path):
    await backend.create_upload(UPLOAD)
    await backend.create_upload("f" * 32)
    await backend.append("f" * 32, pieces(BODY))
    (old,) = [path for path in temporary_files(tmp_path / "store") if path.name.endswith(UPLOAD)]
    long_ago = time.time() - 3 * 86400
    os.utime(old, (long_ago, long_ago))

    removed = await backend.sweep_temporary(86400)

    assert removed == 1
    assert await backend.upload_size(UPLOAD) is None
    assert await backend.upload_size("f" * 32) == len(BODY)
```

`backend/tests/repositories/test_uploads.py`:

```python
import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import service, uploads
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Asset, Upload
from megooarti.repositories.uploads import OutOfOrder, Progress, UnknownUpload
from tests.repositories.conftest import body, someone
from tests.storage.test_races import Factory, create_files, run

EVERYTHING = someone("repository:raw:files")
LAYER = bytes(range(256)) * 40


@pytest.fixture
async def context(files, context_for):
    return await context_for(files, EVERYTHING)


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def temporary_files(settings) -> list[str]:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return [path.name for path in directory.iterdir()] if directory.exists() else []


async def test_an_upload_is_begun_added_to_and_completed(context, db):
    upload = await uploads.begin(context, "app")
    await db.commit()

    first = await uploads.append(context, upload, "app", body(LAYER[:6000]))
    so_far = await uploads.progress(context, upload, "app")
    second = await uploads.append(context, upload, "app", body(LAYER[6000:]), at=6000)
    staged = await uploads.complete(context, upload, "app")
    await context.store("layers/one", staged)
    await db.commit()

    assert len(upload) == 32
    assert (first, second) == (6000, len(LAYER))
    assert so_far == Progress(upload, 6000)
    assert staged.sha256 == hashlib.sha256(LAYER).hexdigest()
    assert await context.read("layers/one", limit=len(LAYER)) == LAYER
    assert await count(db, Upload) == 0


async def test_a_completed_upload_is_over(context, db, settings):
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER))
    staged = await uploads.complete(context, upload, "app")
    await context.discard(staged)
    await db.commit()

    for attempt in (
        uploads.progress(context, upload, "app"),
        uploads.append(context, upload, "app", body(b"more")),
        uploads.complete(context, upload, "app"),
        uploads.abandon(context, upload, "app"),
    ):
        with pytest.raises(UnknownUpload):
            await attempt
    assert temporary_files(settings) == []


async def test_a_chunk_must_start_where_the_upload_ends(context):
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER[:6000]), at=0)

    for start in (0, 5999, 6001, 99999):
        with pytest.raises(OutOfOrder) as refused:
            await uploads.append(context, upload, "app", body(b"chunk"), at=start)
        assert refused.value.size == 6000
    assert (await uploads.progress(context, upload, "app")).size == 6000


async def test_a_chunk_that_stops_arriving_is_taken_back(context):
    async def interrupted() -> AsyncIterator[bytes]:
        yield LAYER[6000:7000]
        raise ConnectionError("the client went away")

    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER[:6000]))

    with pytest.raises(ConnectionError):
        await uploads.append(context, upload, "app", interrupted())

    assert (await uploads.progress(context, upload, "app")).size == 6000


async def test_an_abandoned_upload_leaves_nothing(context, db, settings):
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER))

    await uploads.abandon(context, upload, "app")
    await db.commit()

    assert await count(db, Upload) == 0
    assert temporary_files(settings) == []
    with pytest.raises(UnknownUpload):
        await uploads.progress(context, upload, "app")


@pytest.mark.parametrize(
    "upload_id",
    [
        "0" * 32,  # nobody began it
        "not-an-upload",
        "",
        "../../etc/passwd",
        "0" * 31,
        "G" * 32,
        "ABCDEF0123456789ABCDEF0123456789",  # the one spelling is lower case
        "01234567-89ab-cdef-0123-456789abcdef",
    ],
)
async def test_an_upload_that_was_never_begun_is_unknown(context, upload_id):
    with pytest.raises(UnknownUpload):
        await uploads.progress(context, upload_id, "app")
    with pytest.raises(UnknownUpload):
        await uploads.append(context, upload_id, "app", body(b"x"))


async def test_an_upload_belongs_to_what_it_was_begun_for(context, context_for, db):
    upload = await uploads.begin(context, "app")
    more = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    elsewhere = await context_for(more, someone("repository:raw:more"))

    with pytest.raises(UnknownUpload):
        await uploads.progress(context, upload, "another-app")
    with pytest.raises(UnknownUpload):
        await uploads.append(elsewhere, upload, "app", body(b"x"))
    assert (await uploads.progress(context, upload, "app")).size == 0


async def test_an_upload_needs_the_right_to_write(files, context_for, db):
    writer = await context_for(files, EVERYTHING)
    upload = await uploads.begin(writer, "app")
    await db.commit()
    reader = await context_for(files, someone("repository:raw:files:read"))
    nobody = await context_for(files, None)

    for context, status in ((reader, 403), (nobody, 401)):
        for attempt in (
            uploads.begin(context, "app"),
            uploads.progress(context, upload, "app"),
            uploads.append(context, upload, "app", body(b"x")),
            uploads.complete(context, upload, "app"),
            uploads.abandon(context, upload, "app"),
        ):
            with pytest.raises(ApiError) as refused:
                await attempt
            assert refused.value.status_code == status
    assert (await uploads.progress(writer, upload, "app")).size == 0
    assert await count(db, Asset) == 0


async def test_no_database_connection_is_held_while_a_chunk_arrives(context, db):
    upload = await uploads.begin(context, "app")
    await db.commit()
    in_transaction = []

    async def watched() -> AsyncIterator[bytes]:
        in_transaction.append(db.in_transaction())
        yield LAYER

    await uploads.append(context, upload, "app", watched())

    assert in_transaction == [False]


@pytest.mark.parametrize("stated", [False, True])
def test_two_chunks_that_arrive_together_do_not_mix(empty_database, tmp_path, stated):
    first, second = b"a" * 300_000, b"b" * 300_000

    sending = []

    async def slowly(data: bytes) -> AsyncIterator[bytes]:
        # Stay in the middle of the chunk until the other request is in the middle of
        # its own, or for long enough that it would be if nothing made it wait.
        sending.append(data[:1])
        for _ in range(50):
            if len(sending) == 2:
                break
            await asyncio.sleep(0.01)
        yield data

    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, _ = await create_files(factory)

        async def send(data: bytes) -> int:
            # Each request has a session of its own.
            async with factory() as db:
                sender = await build_context(db, settings, repository, EVERYTHING)
                at = 0 if stated else None
                size = await uploads.append(sender, upload, "app", slowly(data), at=at)
                await db.commit()
                return size

        async with factory() as db:
            upload = await uploads.begin(
                await build_context(db, settings, repository, EVERYTHING), "app"
            )
            await db.commit()

        results = await asyncio.gather(send(first), send(second), return_exceptions=True)

        async with factory() as db:
            context = await build_context(db, settings, repository, EVERYTHING)
            staged = await uploads.complete(context, upload, "app")
            await context.discard(staged)
            await db.commit()
        possible = (first, second) if stated else (first + second, second + first)
        assert staged.sha256 in {hashlib.sha256(data).hexdigest() for data in possible}
        if stated:
            # Both said they were the first chunk. One was; the other is told where to go on.
            refused = [result for result in results if isinstance(result, OutOfOrder)]
            assert [error.size for error in refused] == [300_000]
        else:
            assert sorted(results) == [300_000, 600_000]  # one after the other

    run(empty_database, tmp_path, scenario)


async def test_uploads_nobody_adds_to_are_swept(context, db, sessionmaker, settings):
    old = await uploads.begin(context, "app")
    recent = await uploads.begin(context, "app")
    await uploads.append(context, old, "app", body(LAYER))
    await db.execute(
        update(Upload)
        .where(Upload.key == "app", Upload.id != uploads._identifier(recent))
        .values(updated_at=utcnow() - timedelta(days=2))
    )
    await db.commit()

    removed = await uploads.sweep(sessionmaker, settings, now=utcnow(), max_age_seconds=86400)

    assert removed == 1
    assert [path for path in temporary_files(settings) if path.endswith(old)] == []
    with pytest.raises(UnknownUpload):
        await uploads.progress(context, old, "app")
    assert (await uploads.progress(context, recent, "app")).size == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/storage/test_backends.py tests/repositories/test_uploads.py -q`
Expected: collection error, `cannot import name 'uploads' from 'megooarti.repositories'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/storage/backends.py`:

After

```python
    async def sweep_temporary(self, older_than_seconds: float) -> int: ...
```

add

```python
    async def create_upload(self, upload: str) -> None: ...

    async def upload_size(self, upload: str) -> int | None: ...

    async def append(self, upload: str, chunks: AsyncIterator[bytes]) -> int: ...

    async def adopt(self, upload: str) -> StagedBlob: ...

    async def abandon(self, upload: str) -> None: ...
```

Before

```python
def _sync_directory(directory: Path) -> None:
```

add

```python
def _hash_more(handle: BinaryIO, hashers: dict) -> int:
    """Read the next piece of a file into the hashers. Returns its length, 0 at the end."""
    data = handle.read(CHUNK_SIZE)
    for hasher in hashers.values():
        hasher.update(data)
    return len(data)
```

Before

```python
    async def sweep_temporary(self, older_than_seconds: float) -> int:
        def sweep() -> int:
```

add

```python
    def _upload_path(self, upload: str) -> Path:
        # Under the prefix of everything temporary here, so the sweep covers it too.
        return self._root / "tmp" / f"{_TEMPORARY_PREFIX}chunked-{upload}"

    async def create_upload(self, upload: str) -> None:
        """Make room for an upload that arrives in several pieces. `upload` names it."""

        def create() -> None:
            path = self._upload_path(upload)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

        await asyncio.to_thread(create)

    async def upload_size(self, upload: str) -> int | None:
        """How much of an upload has arrived, or None if there is no such upload."""

        def size() -> int | None:
            try:
                return self._upload_path(upload).stat().st_size
            except FileNotFoundError:
                return None

        return await asyncio.to_thread(size)

    async def append(self, upload: str, chunks: AsyncIterator[bytes]) -> int:
        """Append to an upload and return its size.

        If the chunks stop arriving, what came of them is taken back: an upload only
        ever holds whole appends, so its sender can tell where to go on.
        """
        handle = await asyncio.to_thread(open, self._upload_path(upload), "r+b")
        try:
            start = await asyncio.to_thread(handle.seek, 0, os.SEEK_END)
            pending = bytearray()
            try:
                async for chunk in chunks:
                    pending += chunk
                    while len(pending) >= CHUNK_SIZE:
                        piece = bytes(pending[:CHUNK_SIZE])
                        del pending[:CHUNK_SIZE]
                        await asyncio.to_thread(handle.write, piece)
                if pending:
                    await asyncio.to_thread(handle.write, bytes(pending))
                await asyncio.to_thread(handle.flush)
            except BaseException:
                handle.truncate(start)
                raise
            return await asyncio.to_thread(handle.tell)
        finally:
            handle.close()

    async def adopt(self, upload: str) -> StagedBlob:
        """Turn a finished upload into staged content, hashing it where it lies."""
        path = self._upload_path(upload)
        hashers = {name: hashlib.new(name, usedforsecurity=False) for name in _ALGORITHMS}
        size = 0
        handle = await asyncio.to_thread(open, path, "r+b")
        try:
            # What `commit` will rename into place must be on disk first.
            await asyncio.to_thread(os.fsync, handle.fileno())
            while read := await asyncio.to_thread(_hash_more, handle, hashers):
                size += read
        finally:
            handle.close()
        digests = {name: hasher.hexdigest() for name, hasher in hashers.items()}
        return StagedBlob(token=str(path), size=size, **digests)

    async def abandon(self, upload: str) -> None:
        await asyncio.to_thread(self._upload_path(upload).unlink, True)
```

`backend/src/megooarti/repositories/uploads.py`:

```python
"""Uploads that arrive over several requests.

A container client sends a layer in chunks: one request begins the upload, others
append to it, and a last one completes it. Any container may receive any of them, so
the upload is a row in the database and a file in the blob store's temporary area. On
completion the file is hashed where it lies and becomes staged content, without being
copied.

No database connection is held while a chunk arrives or the file is hashed.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.keyed_locks import KeyedLocks
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.models import Repository, Upload
from megooarti.storage.backends import StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore

# Within this process, chunks for one upload are taken one at a time. A client sends
# them in order; this only keeps two that arrive together from interleaving.
_appending = KeyedLocks()


class UnknownUpload(Exception):
    """There is no such upload in progress in this repository."""


class OutOfOrder(Exception):
    """A chunk does not start where the upload ends. `size` is where it does end."""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size


@dataclass(frozen=True)
class Progress:
    id: str
    size: int


def _identifier(upload_id: str) -> uuid.UUID:
    """The ID as it is stored. It also names a file, so nothing else is accepted."""
    try:
        parsed = uuid.UUID(hex=upload_id)
    except ValueError:
        raise UnknownUpload from None
    if parsed.hex != upload_id:
        raise UnknownUpload  # one spelling only: 32 lower-case hexadecimal digits
    return parsed


async def _row(context: RepositoryContext, upload_id: str, key: str) -> Upload:
    found = await context.db.scalar(
        select(Upload).where(
            Upload.id == _identifier(upload_id),
            Upload.repository_id == context.repository.id,
            Upload.key == key,
        )
    )
    if found is None:
        raise UnknownUpload
    return found


async def begin(context: RepositoryContext, key: str) -> str:
    """Begin an upload for `key`, which is the format's to choose. Returns its ID.

    The caller needs `add` or `edit`. The caller commits.
    """
    context.require_write()
    row = Upload(
        repository_id=context.repository.id,
        key=key,
        created_by=context.principal.user.username,
    )
    context.db.add(row)
    await context.db.flush()
    await context.backend.create_upload(row.id.hex)
    return row.id.hex


async def progress(context: RepositoryContext, upload_id: str, key: str) -> Progress:
    """How much of an upload has arrived. Raises UnknownUpload."""
    context.require_write()
    await _row(context, upload_id, key)
    size = await context.backend.upload_size(upload_id)
    if size is None:
        raise UnknownUpload
    return Progress(upload_id, size)


async def append(
    context: RepositoryContext,
    upload_id: str,
    key: str,
    chunks: AsyncIterator[bytes],
    *,
    at: int | None = None,
) -> int:
    """Append a chunk and return the upload's size. The caller commits.

    `at` is where the client says the chunk starts. If the upload does not end
    there, nothing is appended and OutOfOrder says where it does end. A chunk that
    stops arriving half-way is taken back, so the size is always that of whole chunks.
    """
    context.require_write()
    await _row(context, upload_id, key)
    await context.release()  # the chunk needs no connection
    async with _appending.hold(upload_id):
        size = await context.backend.upload_size(upload_id)
        if size is None:
            raise UnknownUpload
        if at is not None and at != size:
            raise OutOfOrder(size)
        size = await context.backend.append(upload_id, chunks)
    await context.db.execute(
        update(Upload).where(Upload.id == _identifier(upload_id)).values(updated_at=utcnow())
    )
    return size


async def complete(context: RepositoryContext, upload_id: str, key: str) -> StagedBlob:
    """Turn an upload into staged content, ready for `context.store`. The caller commits.

    The upload is over whatever the caller then does with the content: store it, or
    `context.discard` it.
    """
    context.require_write()
    await _row(context, upload_id, key)
    await context.release()  # hashing the file needs no connection
    async with _appending.hold(upload_id):
        if await context.backend.upload_size(upload_id) is None:
            raise UnknownUpload
        staged = await context.backend.adopt(upload_id)
    await context.db.execute(delete(Upload).where(Upload.id == _identifier(upload_id)))
    return staged


async def abandon(context: RepositoryContext, upload_id: str, key: str) -> None:
    """Give an upload up. Raises UnknownUpload. The caller commits."""
    context.require_write()
    row = await _row(context, upload_id, key)
    await context.db.delete(row)
    await context.backend.abandon(upload_id)


async def sweep(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
    max_age_seconds: int,
) -> int:
    """Remove uploads nothing was appended to for `max_age_seconds`. Returns how many."""
    cutoff = now - timedelta(seconds=max_age_seconds)
    async with sessionmaker() as db:
        stale = (
            await db.execute(
                select(Upload.id, Repository.blob_store_id)
                .join(Repository, Repository.id == Upload.repository_id)
                .where(Upload.updated_at < cutoff)
            )
        ).all()
        stores = {store.id: store for store in await db.scalars(select(BlobStore))}
        for upload_id, store_id in stale:
            if store_id in stores:
                await backend_for(settings, stores[store_id]).abandon(upload_id.hex)
            await db.execute(delete(Upload).where(Upload.id == upload_id))
        await db.commit()
    return len(stale)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/storage tests/repositories/test_uploads.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/storage/backends.py backend/src/megooarti/repositories/uploads.py backend/tests/storage/test_backends.py backend/tests/repositories/test_uploads.py
git commit -m "feat(repositories): uploads that arrive over several requests"
```

---

### Task 4: Core: where a format is served, and upkeep

**Files:**
- Create: `backend/src/megooarti/repositories/upkeep.py`
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/routes.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/repositories/test_upkeep.py`

**Interfaces:**
- Consumes: `uploads.sweep` (Task 3); `build_context`, `get_format`; the compaction job in `main.py`.
- Produces:
  - `Format.served_at: str = "repository"`. A format served by the registry API sets `"registry"`. The content route answers `404 not_found` for a repository whose format is served elsewhere.
  - `await Format.maintain(context, now: datetime) -> None`: does nothing by default. The context has no principal. Does not commit.
  - `await upkeep.run(sessionmaker, settings, now) -> None`, and `upkeep.UPLOAD_MAX_AGE_SECONDS = 86400`. The periodic job calls it before `blobs.compact`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_upkeep.py`:

```python
from datetime import timedelta

import structlog
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.repositories import formats, service, upkeep, uploads
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset, Upload
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import body, someone


class Tidy(Format):
    """A format that, as upkeep, removes what is under `scratch/`."""

    name = "raw"

    def __init__(self) -> None:
        self.tended: list[tuple[str, object]] = []

    async def maintain(self, context, now):
        self.tended.append((context.repository.name, context.principal))
        if context.repository.name == "broken":
            raise RuntimeError("this one cannot be tended")
        for path in await context.present(["scratch/a", "scratch/b"]):
            await context.sweep(path)


async def create(db, name: str):
    repository = await service.create_repository(
        db, name=name, format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    return repository


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_every_format_tends_its_repositories(
    db, sessionmaker, settings, context_for, monkeypatch
):
    tidy = Tidy()
    monkeypatch.setitem(formats._registry, "raw", tidy)
    for name in ("alpha", "broken", "gamma"):
        repository = await create(db, name)
        writer = await context_for(repository, someone(f"repository:raw:{name}"))
        await writer.put("scratch/a", body(b"left over"))
        await writer.put("kept/a", body(b"wanted"))
    await db.commit()

    with structlog.testing.capture_logs() as logs:
        await upkeep.run(sessionmaker, settings, utcnow())

    assert tidy.tended == [("alpha", None), ("broken", None), ("gamma", None)]
    kept = await db.scalars(select(Asset.path).order_by(Asset.path))
    assert list(kept) == ["kept/a", "kept/a", "kept/a", "scratch/a"]  # only broken's is left
    failed = [entry for entry in logs if entry["event"] == "upkeep_failed"]
    assert [entry["repository"] for entry in failed] == ["broken"]


async def test_the_generic_format_needs_no_upkeep(db, sessionmaker, settings, files, context_for):
    writer = await context_for(files, someone("repository:raw:files"))
    await writer.put("scratch/a", body(b"left alone"))
    await db.commit()

    await upkeep.run(sessionmaker, settings, utcnow())

    assert await count(db, Asset) == 1


async def test_uploads_that_were_left_are_removed(db, sessionmaker, settings, files, context_for):
    writer = await context_for(files, someone("repository:raw:files"))
    old = await uploads.begin(writer, "app")
    await uploads.begin(writer, "app")
    await db.execute(
        update(Upload)
        .where(Upload.id == uploads._identifier(old))
        .values(updated_at=utcnow() - timedelta(days=2))
    )
    await db.commit()

    await upkeep.run(sessionmaker, settings, utcnow())

    assert await count(db, Upload) == 1


class Elsewhere(Format):
    """A format whose repositories are reached through a protocol of their own."""

    name = "raw"
    served_at = "registry"


async def test_a_format_served_elsewhere_is_not_served_under_repository(
    client, files, make_user, monkeypatch
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    await client.put("/repository/files/a.txt", content=b"x", headers=root)
    monkeypatch.setitem(formats._registry, "raw", Elsewhere())

    read = await client.get("/repository/files/a.txt", headers=root)
    written = await client.put("/repository/files/b.txt", content=b"y", headers=root)
    without_credentials = await client.get("/repository/files/a.txt")
    unknown = await client.get("/repository/no-such-repository/a.txt")

    for response in (read, written, without_credentials):
        assert (response.status_code, error_code(response)) == (404, "not_found")
    # To someone who has not signed in, it looks like a repository that does not exist.
    assert without_credentials.status_code == unknown.status_code


def test_formats_are_served_under_repository_unless_they_say_otherwise():
    assert Format.served_at == "repository"
    assert all(
        formats.get_format(name).served_at == "repository"
        for name in ("raw", "maven", "npm", "pypi")
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_upkeep.py -q`
Expected: collection error, `cannot import name 'upkeep' from 'megooarti.repositories'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`:

After

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
```

add

```python
from datetime import datetime
```

After

```python
    name: str = ""
    types: frozenset[str] = frozenset({"hosted", "proxy", "group"})
```

add

```python
    # Where clients reach repositories of this format: under /repository/<name>/, or
    # through a protocol with an address of its own, which then has its own routes.
    served_at: str = "repository"
```

Before

```python
    async def handle_hosted(
        self, context: "RepositoryContext", request: Request, path: str
    ) -> Response:
        """Answer a request to a hosted repository. The route has checked `read`.
```

add

```python
    async def maintain(self, context: "RepositoryContext", now: datetime) -> None:
        """Do what one repository needs done from time to time. The generic format: nothing.

        Called by the maintenance job, not for a request: nobody is calling, so the
        context has no principal, and only what needs none can be used. Does not commit.
        """
```

In `backend/src/megooarti/repositories/routes.py`:

After

```python
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
```

add

```python
    if handler is not None and handler.served_at != "repository":
        raise ApiError(
            404, "not_found", "This repository is not served here: its format has its own address."
        )
```

`backend/src/megooarti/repositories/upkeep.py`:

```python
"""What repositories need done from time to time, whoever uses them.

Run by the periodic maintenance job. Each format tends its own repositories; uploads
that were begun and then left are removed here, for every format.
"""

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.config import Settings
from megooarti.repositories import uploads
from megooarti.repositories.content import build_context
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Repository

log = structlog.get_logger(__name__)

# An upload nothing was appended to for this long is given up on.
UPLOAD_MAX_AGE_SECONDS = 86400


async def run(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> None:
    """Let every format tend its repositories, then remove uploads that were left.

    One repository's failure is logged and does not stop the others.
    """
    async with sessionmaker() as db:
        identifiers = list(await db.scalars(select(Repository.id).order_by(Repository.name_key)))
    for identifier in identifiers:
        async with sessionmaker() as db:
            repository = await db.get(Repository, identifier)
            handler = None if repository is None else get_format(repository.format)
            if handler is None:
                continue  # deleted since, or of a format this version does not have
            try:
                # Nobody is calling, so there is no principal.
                context = await build_context(db, settings, repository, None)
                await handler.maintain(context, now)
                await db.commit()
            except Exception:
                log.error("upkeep_failed", repository=repository.name, exc_info=True)
    removed = await uploads.sweep(
        sessionmaker, settings, now=now, max_age_seconds=UPLOAD_MAX_AGE_SECONDS
    )
    log.info("upkeep_finished", repositories=len(identifiers), uploads_removed=removed)
```

In `backend/src/megooarti/main.py`:

After

```python
from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
```

add

```python
from megooarti.repositories import upkeep
```

Replace

```python
    async def job() -> None:
        removed = await blobs.compact(
```

with

```python
    async def job() -> None:
        # First, so that what upkeep removes starts its wait for compaction now.
        await upkeep.run(app.state.sessionmaker, settings, utcnow())
        removed = await blobs.compact(
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_upkeep.py tests/test_maintenance.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/src/megooarti/main.py backend/tests/repositories/test_upkeep.py
git commit -m "feat(repositories): a format says where it is served and tends its repositories"
```

---

### Task 5: Docker names, manifests and errors

**Files:**
- Create: `backend/src/megooarti/repositories/docker/__init__.py`
- Create: `backend/src/megooarti/repositories/docker/names.py`
- Create: `backend/src/megooarti/repositories/docker/manifests.py`
- Create: `backend/src/megooarti/repositories/docker/errors.py`
- Test: `backend/tests/repositories/docker/__init__.py`
- Test: `backend/tests/repositories/docker/test_names.py`
- Test: `backend/tests/repositories/docker/test_manifests.py`

**Interfaces:**
- Consumes: `ApiError`.
- Produces:
  - `names.DockerPath(kind: str, image: str = "", reference: str = "")`, where `kind` is `manifest`, `blob`, `upload_start`, `upload`, `tags`, `referrers` or `other`.
  - `names.classify(path: str) -> DockerPath`, for the part of the address after the repository.
  - `names.is_valid_name`, `names.is_tag`, `names.is_digest`, `names.hex_of(digest) -> str`, `names.blob_path(digest) -> str`, `names.manifest_path(image, digest) -> str`, `names.tag_path(image, tag) -> str`, `names.tag_of(path) -> tuple[str, str] | None`, `names.MAX_NAME_LENGTH = 255`.
  - `manifests.DOCKER_MANIFEST`, `manifests.DOCKER_LIST`, `manifests.OCI_MANIFEST`, `manifests.OCI_INDEX`, `manifests.MAX_BYTES`, `manifests.InvalidManifest`, `manifests.Manifest(media_type, digest, blobs: tuple[str, ...], manifests: tuple[str, ...])`, `manifests.read(raw: bytes, declared: str | None) -> Manifest`.
  - `errors.RegistryError(status, code, message, detail=None, headers=None)`, an `ApiError`; `errors.unknown(code, message) -> RegistryError` (a `404`); `errors.response(error: ApiError, headers=None) -> JSONResponse`; `errors.API_VERSION`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/docker/__init__.py`:

```python

```

`backend/tests/repositories/docker/test_names.py`:

```python
import pytest

from megooarti.repositories.docker import names
from megooarti.repositories.docker.names import DockerPath, classify

DIGEST = "sha256:" + "a" * 64
UPLOAD = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "image",
    [
        "app",
        "team/app",
        "a/b/c/d",
        "my-app",
        "my--app",
        "my_app",
        "my__app",
        "my.app",
        "0",
        "a1/b2",
    ],
)
def test_valid_image_names(image):
    assert names.is_valid_name(image)


@pytest.mark.parametrize(
    "image",
    [
        "",
        "App",
        "team/App",
        "-app",
        "app-",
        "app..x",
        "app___x",
        "app_.x",
        "/app",
        "app/",
        "a//b",
        "a b",
        "app:latest",
        "app@sha256",
        "ünï",
        "a" * 256,
        "../app",
        ".",
    ],
)
def test_invalid_image_names(image):
    assert not names.is_valid_name(image)


@pytest.mark.parametrize("tag", ["latest", "1.0", "v1.0.0-rc.1", "_internal", "A", "a" * 128, "1"])
def test_valid_tags(tag):
    assert names.is_tag(tag)


@pytest.mark.parametrize(
    "tag", ["", ".hidden", "-dash", "a" * 129, "a/b", "a:b", "a b", DIGEST, "é"]
)
def test_invalid_tags(tag):
    assert not names.is_tag(tag)


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:" + "A" * 64,  # one spelling: lower case
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha256:" + "g" * 64,
        "sha512:" + "a" * 128,
        "a" * 64,
        "sha256:",
        "",
    ],
)
def test_only_a_lower_case_sha256_is_a_digest(digest):
    assert names.is_digest(DIGEST)
    assert not names.is_digest(digest)
    assert names.hex_of(DIGEST) == "a" * 64


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/manifests/latest", DockerPath("manifest", "app", "latest")),
        (f"app/manifests/{DIGEST}", DockerPath("manifest", "app", DIGEST)),
        (f"team/app/blobs/{DIGEST}", DockerPath("blob", "team/app", DIGEST)),
        ("team/app/blobs/uploads/", DockerPath("upload_start", "team/app")),
        ("team/app/blobs/uploads", DockerPath("upload_start", "team/app")),
        (f"app/blobs/uploads/{UPLOAD}", DockerPath("upload", "app", UPLOAD)),
        ("a/b/c/tags/list", DockerPath("tags", "a/b/c")),
        (f"app/referrers/{DIGEST}", DockerPath("referrers", "app", DIGEST)),
        # A name may contain the words a path is read by. It is read from its end.
        ("manifests/manifests/latest", DockerPath("manifest", "manifests", "latest")),
        ("blobs/tags/tags/list", DockerPath("tags", "blobs/tags")),
        ("tags/list/manifests/v1", DockerPath("manifest", "tags/list", "v1")),
        (f"a/blobs/uploads/blobs/{DIGEST}", DockerPath("blob", "a/blobs/uploads", DIGEST)),
    ],
)
def test_paths_are_classified(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "",
        "app",
        "app/",
        "manifests/latest",  # no image
        "/manifests/latest",
        "App/manifests/latest",
        "app/manifests/",
        "app/manifests/-bad",
        "app/manifests/a/b",
        "app/manifests/sha512:" + "a" * 128,
        "app/blobs/latest",
        "app/blobs/sha256:" + "A" * 64,
        f"app/blobs/{DIGEST}/extra",
        "app/blobs/uploads/not-an-upload",
        f"app/blobs/uploads/{UPLOAD}/more",
        "app/blobs/uploads/" + UPLOAD.upper(),
        "app/tags",
        "app/tags/list/",
        "tags/list",
        "app/referrers/latest",
        "../app/manifests/latest",
        "app/../manifests/latest",
    ],
)
def test_everything_else_is_other(path):
    assert classify(path).kind == "other"


def test_stored_paths():
    assert names.blob_path(DIGEST) == f"blobs/{DIGEST}"
    assert names.manifest_path("team/app", DIGEST) == f"manifests/team/app/{DIGEST}"
    assert names.tag_path("team/app", "v1") == "tags/team/app/v1"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tags/app/latest", ("app", "latest")),
        ("tags/team/app/v1.0", ("team/app", "v1.0")),
        ("tags/tags/tags", ("tags", "tags")),
        (f"manifests/app/{DIGEST}", None),
        (f"blobs/{DIGEST}", None),
        ("tags/app", None),
        ("tags/app/", None),
        ("tags/App/latest", None),
        ("tags/app/-bad", None),
        ("tags", None),
        ("", None),
    ],
)
def test_a_stored_tag_names_its_image(path, expected):
    assert names.tag_of(path) == expected
```

`backend/tests/repositories/docker/test_manifests.py`:

```python
import hashlib
import json

import pytest

from megooarti.errors import ApiError
from megooarti.repositories.docker import errors, manifests
from megooarti.repositories.docker.errors import RegistryError
from megooarti.repositories.docker.manifests import (
    DOCKER_LIST,
    DOCKER_MANIFEST,
    OCI_INDEX,
    OCI_MANIFEST,
    InvalidManifest,
)

CONFIG = "sha256:" + "c" * 64
LAYER_ONE = "sha256:" + "1" * 64
LAYER_TWO = "sha256:" + "2" * 64
AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64


def image(media_type: str | None = OCI_MANIFEST, **changes) -> bytes:
    document = {
        "schemaVersion": 2,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": CONFIG},
        "layers": [{"digest": LAYER_ONE, "size": 10}, {"digest": LAYER_TWO, "size": 20}],
    }
    if media_type is not None:
        document["mediaType"] = media_type
    document.update(changes)
    return json.dumps(document).encode()


def index(media_type: str | None = OCI_INDEX, **changes) -> bytes:
    document = {
        "schemaVersion": 2,
        "manifests": [
            {"digest": AMD64, "platform": {"architecture": "amd64", "os": "linux"}},
            {"digest": ARM64, "platform": {"architecture": "arm64", "os": "linux"}},
        ],
    }
    if media_type is not None:
        document["mediaType"] = media_type
    document.update(changes)
    return json.dumps(document).encode()


@pytest.mark.parametrize("media_type", [OCI_MANIFEST, DOCKER_MANIFEST])
def test_an_image_refers_to_its_configuration_and_its_layers(media_type):
    raw = image(media_type)

    read = manifests.read(raw, media_type)

    assert read.media_type == media_type
    assert read.digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert read.blobs == (CONFIG, LAYER_ONE, LAYER_TWO)
    assert read.manifests == ()


@pytest.mark.parametrize("media_type", [OCI_INDEX, DOCKER_LIST])
def test_a_list_refers_to_the_manifest_of_each_platform(media_type):
    read = manifests.read(index(media_type), media_type)

    assert (read.media_type, read.blobs, read.manifests) == (media_type, (), (AMD64, ARM64))


@pytest.mark.parametrize(
    ("raw", "declared", "expected"),
    [
        (image(DOCKER_MANIFEST), None, DOCKER_MANIFEST),  # only the manifest says
        (image(DOCKER_MANIFEST), "application/json", DOCKER_MANIFEST),
        (image(None), OCI_MANIFEST, OCI_MANIFEST),  # only the request says
        (image(None), f"{DOCKER_MANIFEST}; charset=utf-8", DOCKER_MANIFEST),
        (image(None), None, OCI_MANIFEST),  # neither says: what it holds decides
        (index(None), "", OCI_INDEX),
        (image(OCI_MANIFEST), OCI_MANIFEST.upper(), OCI_MANIFEST),
    ],
)
def test_the_kind_is_what_the_request_or_the_manifest_says(raw, declared, expected):
    assert manifests.read(raw, declared).media_type == expected


def test_a_layer_kept_elsewhere_need_not_be_here():
    foreign = {"digest": LAYER_TWO, "urls": ["https://elsewhere.example/layer"]}
    raw = image(layers=[{"digest": LAYER_ONE}, foreign, {"digest": LAYER_ONE, "urls": []}])

    assert manifests.read(raw, None).blobs == (CONFIG, LAYER_ONE)  # each once


def test_an_artifact_is_an_image_like_any_other():
    empty = {"mediaType": "application/vnd.oci.empty.v1+json", "digest": CONFIG, "size": 2}
    raw = image(config=empty, artifactType="application/vnd.example.chart", subject={})

    assert manifests.read(raw, OCI_MANIFEST).blobs == (CONFIG, LAYER_ONE, LAYER_TWO)


def test_the_digest_is_of_the_bytes_as_pushed():
    spaced = json.dumps(json.loads(image()), indent=3).encode()

    assert manifests.read(spaced, None).digest != manifests.read(image(), None).digest
    assert manifests.read(spaced, None).blobs == manifests.read(image(), None).blobs


@pytest.mark.parametrize(
    ("raw", "declared", "reason"),
    [
        (b"not json", None, "not JSON"),
        (b"\xff\xfe", None, "not JSON"),
        (b"[]", None, "not a JSON object"),
        (image(schemaVersion=1), None, "schemaVersion"),
        (image(schemaVersion=True), None, "schemaVersion"),
        (image(schemaVersion="2"), None, "schemaVersion"),
        (
            image("application/vnd.docker.distribution.manifest.v1+json"),
            None,
            "not a manifest type",
        ),
        (
            image(None),
            "application/vnd.docker.distribution.manifest.v1+prettyjws",
            "not a manifest",
        ),
        (image(OCI_MANIFEST), DOCKER_MANIFEST, "Content-Type"),
        (image(mediaType=7), None, "mediaType"),
        (image(config=None), None, "configuration"),
        (image(config={"digest": "sha512:" + "a" * 128}), None, "configuration"),
        (image(config={"digest": "sha256:" + "A" * 64}), None, "configuration"),
        (image(layers=None), None, "no layers"),
        (image(layers=[{"size": 3}]), None, "a layer"),
        (image(layers=["sha256:" + "1" * 64]), None, "a layer"),
        (index(manifests=None), None, "no manifests"),
        (index(manifests=[{"digest": "latest"}]), None, "a listed manifest"),
        (image(OCI_INDEX), None, "no manifests"),  # says it is a list, holds an image
    ],
)
def test_what_is_not_a_manifest_this_registry_takes(raw, declared, reason):
    with pytest.raises(InvalidManifest, match=reason):
        manifests.read(raw, declared)


def test_a_manifest_nested_too_deep_or_too_large_is_refused():
    with pytest.raises(InvalidManifest, match="not JSON"):
        manifests.read(b"[" * 100_000, None)
    with pytest.raises(InvalidManifest, match="larger than 4 MiB"):
        manifests.read(image() + b" " * manifests.MAX_BYTES, None)
    assert manifests.read(image() + b" " * 1000, None).blobs  # space after it is still JSON


def test_an_error_is_answered_in_the_registrys_shape():
    error = RegistryError(404, "BLOB_UNKNOWN", "No such blob.", detail={"digest": CONFIG})

    answer = errors.response(error)

    assert answer.status_code == 404
    assert json.loads(answer.body) == {
        "errors": [
            {"code": "BLOB_UNKNOWN", "message": "No such blob.", "detail": {"digest": CONFIG}}
        ]
    }
    assert answer.headers["Docker-Distribution-Api-Version"] == "registry/2.0"
    assert isinstance(error, ApiError) and error.code == "BLOB_UNKNOWN"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "UNAUTHORIZED"),
        (403, "DENIED"),
        (404, "NAME_UNKNOWN"),
        (405, "UNSUPPORTED"),
        (409, "DENIED"),
        (413, "SIZE_INVALID"),
        (429, "TOOMANYREQUESTS"),
        (502, "UNKNOWN"),
        (503, "UNKNOWN"),
    ],
)
def test_an_error_of_the_cores_gets_the_code_that_fits_its_status(status, code):
    core = ApiError(status, "something_ours", "What happened.", headers={"Retry-After": "7"})

    answer = errors.response(core, headers={"WWW-Authenticate": "Bearer"})

    assert answer.status_code == status
    assert json.loads(answer.body) == {"errors": [{"code": code, "message": "What happened."}]}
    assert answer.headers["Retry-After"] == "7"
    assert answer.headers["WWW-Authenticate"] == "Bearer"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/docker -q`
Expected: 2 collection errors, `No module named 'megooarti.repositories.docker'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/docker/__init__.py`:

```python

```

`backend/src/megooarti/repositories/docker/names.py`:

```python
"""Container image names, tags and digests, and what a registry request path means.

Pure functions. A request under `/v2/<repository>/` names an image and then says what
is wanted of it; an image's name may itself contain slashes, so a path is read from
its end.
"""

import re
from dataclasses import dataclass

# An image's name with its repository in front, as a client writes it.
MAX_NAME_LENGTH = 255
_COMPONENT = r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
_NAME = re.compile(rf"{_COMPONENT}(?:/{_COMPONENT})*")
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_UPLOAD = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class DockerPath:
    """A request path, classified. Fields that do not apply to its kind are left empty."""

    # manifest, blob, upload_start, upload, tags, referrers or other
    kind: str
    image: str = ""
    reference: str = ""  # manifest: a tag or a digest; blob, referrers: a digest; upload: its ID


_OTHER = DockerPath("other")


def is_valid_name(image: str) -> bool:
    return len(image) <= MAX_NAME_LENGTH and _NAME.fullmatch(image) is not None


def is_tag(text: str) -> bool:
    return _TAG.fullmatch(text) is not None


def is_digest(text: str) -> bool:
    """Whether this is a digest this registry takes: SHA-256, in lower case."""
    return _DIGEST.fullmatch(text) is not None


def hex_of(digest: str) -> str:
    """The hash in a digest: `sha256:<hex>` without its algorithm."""
    return digest.partition(":")[2]


def blob_path(digest: str) -> str:
    """Where a layer or an image configuration is stored: once for the repository."""
    return f"blobs/{digest}"


def manifest_path(image: str, digest: str) -> str:
    return f"manifests/{image}/{digest}"


def tag_path(image: str, tag: str) -> str:
    """Where a tag is stored: a file that holds the manifest the tag names."""
    return f"tags/{image}/{tag}"


def tag_of(path: str) -> tuple[str, str] | None:
    """The image and the tag a stored path is for, or None if it is not a tag's."""
    kind, _, rest = path.partition("/")
    image, _, tag = rest.rpartition("/")
    if kind != "tags" or not is_valid_name(image) or not is_tag(tag):
        return None
    return image, tag


def _split(path: str, marker: str) -> tuple[str, str] | None:
    """The image before the last `marker` and what follows it, if the image is one."""
    image, found, rest = path.rpartition(marker)
    if not found or not is_valid_name(image):
        return None
    return image, rest


def classify(path: str) -> DockerPath:
    """What a request path under `/v2/<repository>/` asks for."""
    if path.endswith("/tags/list"):
        image = path.removesuffix("/tags/list")
        return DockerPath("tags", image) if is_valid_name(image) else _OTHER
    found = _split(path, "/blobs/uploads/")
    if found is not None and found[1] == "":
        return DockerPath("upload_start", found[0])
    if found is not None and _UPLOAD.fullmatch(found[1]):
        return DockerPath("upload", found[0], found[1])
    if path.endswith("/blobs/uploads"):
        image = path.removesuffix("/blobs/uploads")
        return DockerPath("upload_start", image) if is_valid_name(image) else _OTHER
    for marker, kind in (("/blobs/", "blob"), ("/referrers/", "referrers")):
        found = _split(path, marker)
        if found is not None and is_digest(found[1]):
            return DockerPath(kind, found[0], found[1])
    found = _split(path, "/manifests/")
    if found is not None and (is_tag(found[1]) or is_digest(found[1])):
        return DockerPath("manifest", found[0], found[1])
    return _OTHER
```

`backend/src/megooarti/repositories/docker/manifests.py`:

```python
"""Container image manifests: what one is, and what it refers to.

Pure functions. A manifest is kept and served exactly as it was pushed, because its
digest is the hash of those bytes. It is read here only to learn its kind and the
blobs and manifests it needs.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from megooarti.repositories.docker import names

DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
DOCKER_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
# One image, and several images for several platforms.
_IMAGES = (DOCKER_MANIFEST, OCI_MANIFEST)
_LISTS = (DOCKER_LIST, OCI_INDEX)
MAX_BYTES = 4 * 1024 * 1024


class InvalidManifest(Exception):
    """What was pushed is not a manifest this registry takes. The message says why."""


@dataclass(frozen=True)
class Manifest:
    media_type: str
    digest: str  # `sha256:<hex>` of the bytes as pushed
    blobs: tuple[str, ...]  # digests of the configuration and layers it needs
    manifests: tuple[str, ...]  # digests of its platforms' manifests, if it is a list


def _digest_in(descriptor: Any, what: str) -> str:
    digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    if not isinstance(digest, str) or not names.is_digest(digest):
        raise InvalidManifest(f"{what} has no SHA-256 digest")
    return digest


def _kind(document: dict[str, Any], declared: str | None) -> str:
    """The media type: what the request declared, or what the manifest says of itself."""
    stated = document.get("mediaType")
    if stated is not None and not isinstance(stated, str):
        raise InvalidManifest("its mediaType is not text")
    sent = (declared or "").partition(";")[0].strip().lower()
    if sent in ("", "application/json", "application/octet-stream"):
        sent = ""  # says nothing about which kind of manifest it is
    if sent and stated and sent != stated:
        raise InvalidManifest("its mediaType is not the Content-Type it was sent with")
    kind = sent or stated
    if not kind:
        # OCI lets the type be left out. What the document holds says which it is.
        kind = OCI_INDEX if "manifests" in document else OCI_MANIFEST
    if kind not in _IMAGES + _LISTS:
        raise InvalidManifest(f"{kind} is not a manifest type this registry takes")
    return kind


def read(raw: bytes, declared: str | None) -> Manifest:
    """Read a manifest as pushed. `declared` is the request's Content-Type.

    Raises InvalidManifest.
    """
    if len(raw) > MAX_BYTES:
        raise InvalidManifest("it is larger than 4 MiB")
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise InvalidManifest("it is not JSON") from None
    if not isinstance(document, dict):
        raise InvalidManifest("it is not a JSON object")
    version = document.get("schemaVersion")
    if version != 2 or isinstance(version, bool):
        raise InvalidManifest("its schemaVersion is not 2")
    kind = _kind(document, declared)

    blobs: list[str] = []
    manifests: list[str] = []
    if kind in _LISTS:
        listed = document.get("manifests")
        if not isinstance(listed, list):
            raise InvalidManifest("it lists no manifests")
        manifests = [_digest_in(entry, "a listed manifest") for entry in listed]
    else:
        layers = document.get("layers")
        if not isinstance(layers, list):
            raise InvalidManifest("it has no layers")
        blobs.append(_digest_in(document.get("config"), "its configuration"))
        for layer in layers:
            digest = _digest_in(layer, "a layer")
            # A layer that says where else it is kept need not be here.
            if not (isinstance(layer.get("urls"), list) and layer["urls"]):
                blobs.append(digest)
    return Manifest(
        media_type=kind,
        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        blobs=tuple(dict.fromkeys(blobs)),
        manifests=tuple(dict.fromkeys(manifests)),
    )
```

`backend/src/megooarti/repositories/docker/errors.py`:

```python
"""Errors in the registry's own shape.

Container clients show a registry's error codes to their users, so under `/v2/` an
error is `{"errors": [{"code", "message", "detail"}]}`, not MegooArti's envelope. This
is the one API that does not use the standard one.
"""

from typing import Any

from starlette.responses import JSONResponse

from megooarti.errors import ApiError

API_VERSION = {"Docker-Distribution-Api-Version": "registry/2.0"}
# For an error raised by the core in MegooArti's own shape: the code that fits its status.
_BY_STATUS = {
    400: "UNSUPPORTED",
    401: "UNAUTHORIZED",
    403: "DENIED",
    404: "NAME_UNKNOWN",
    405: "UNSUPPORTED",
    409: "DENIED",
    413: "SIZE_INVALID",
    416: "BLOB_UPLOAD_INVALID",
    429: "TOOMANYREQUESTS",
}


class RegistryError(ApiError):
    """An error with one of the registry's codes. `code` is that code, in upper case."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, code, message, headers=headers)
        self.detail = detail


def unknown(code: str, message: str) -> RegistryError:
    """`404` for something of a kind the registry names: a blob, a manifest, an upload."""
    return RegistryError(404, code, message)


def response(error: ApiError, headers: dict[str, str] | None = None) -> JSONResponse:
    """The answer for an error raised anywhere beneath a registry route."""
    if isinstance(error, RegistryError):
        code, detail = error.code, error.detail
    else:
        code, detail = _BY_STATUS.get(error.status_code, "UNKNOWN"), None
    entry: dict[str, Any] = {"code": code, "message": error.message}
    if detail is not None:
        entry["detail"] = detail
    return JSONResponse(
        {"errors": [entry]},
        status_code=error.status_code,
        headers={**API_VERSION, **(error.headers or {}), **(headers or {})},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/docker -q`
Expected: 142 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/docker backend/tests/repositories/docker
git commit -m "feat(docker): image names, manifests and the registry's errors"
```

---

### Task 6: The registry API and hosted Docker

**Files:**
- Create: `backend/src/megooarti/repositories/docker/format.py`
- Create: `backend/src/megooarti/repositories/docker/routes.py`
- Modify: `backend/src/megooarti/repositories/service.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `backend/tests/test_route_guards.py`
- Test: `backend/tests/repositories/docker/conftest.py`
- Test: `backend/tests/repositories/docker/test_registry.py`
- Test: `backend/tests/repositories/docker/test_push.py`
- Test: `backend/tests/repositories/docker/test_images.py`
- Test: `backend/tests/repositories/docker/test_races.py`

**Interfaces:**
- Consumes: `issue_registry_token`, `client_credentials`, `Credentials.principal`, `authorize` (Task 1); `context.lock`, `context.present`, `context.references`, `context.referenced`, `context.unreferenced`, `context.sweep`, `context.store(..., references=)` (Task 2); the `uploads` module (Task 3); `Format.served_at`, `Format.maintain` (Task 4); `names`, `manifests`, `errors` (Task 5); `context.stat`, `context.respond`, `context.receive`, `context.stage`, `context.stage_bytes`, `context.discard`, `context.delete`, `context.require_write`, `context.release`, `context.versions`, `context.package_names`, `context.package_files`; `dispatch.serve`; `build_context`.
- Produces:
  - `await service.repositories_of(db, format: str) -> list[Repository]`.
  - The format `docker`, registered when `megooarti.repositories.docker.routes` is imported: `served_at = "registry"`, `types = {"hosted"}`, a component for each tag, `maintain` that removes blobs no manifest has referred to for `UNUSED_BLOB_SECONDS` (a day).
  - `await format.images(context) -> list[str]`: the images of a repository that have a tag.
  - Routes `GET /v2/`, `GET /v2/token`, `GET /v2/_catalog` and `/v2/{name}/{path:path}`, none of them in the OpenAPI document.
  - Test helpers in `tests/repositories/docker/conftest.py`: `V2`, `create`, `digest_of`, `layer`, `config_for`, `image_manifest`, `index_manifest`, `push_blob`, `push_manifest`, `push_image`, `error_code`, and the fixtures `images` (a hosted repository named `images`) and `root` (an administrator's Basic credentials).

- [ ] **Step 1: Write the test helpers and the failing tests**

`backend/tests/repositories/docker/conftest.py`:

```python
import hashlib
import json

import pytest

from megooarti.repositories import service
from megooarti.repositories.docker.manifests import OCI_INDEX, OCI_MANIFEST
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

V2 = "/v2/images"


async def create(db, name: str, *, hosted: dict | None = None) -> Repository:
    """A hosted Docker repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="docker",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config={},
    )
    await db.commit()
    return repository


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def layer(text: str) -> bytes:
    """Stand-in layer bytes, different for every text."""
    return f"\x1f\x8b a layer holding {text}".encode()


def image_manifest(config: bytes, *layers: bytes, media_type: str = OCI_MANIFEST) -> bytes:
    """The manifest of an image with this configuration and these layers."""
    document = {
        "schemaVersion": 2,
        "mediaType": media_type,
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": digest_of(config),
            "size": len(config),
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": digest_of(data),
                "size": len(data),
            }
            for data in layers
        ],
    }
    return json.dumps(document).encode()


def index_manifest(*platforms: bytes, media_type: str = OCI_INDEX) -> bytes:
    """A manifest for several platforms, each given as its own manifest."""
    architectures = ("amd64", "arm64", "riscv64", "s390x")
    document = {
        "schemaVersion": 2,
        "mediaType": media_type,
        "manifests": [
            {
                "mediaType": OCI_MANIFEST,
                "digest": digest_of(manifest),
                "size": len(manifest),
                "platform": {"architecture": architectures[position], "os": "linux"},
            }
            for position, manifest in enumerate(platforms)
        ],
    }
    return json.dumps(document).encode()


def config_for(*texts: str) -> bytes:
    """The configuration of the image `push_image` makes of these layers."""
    return json.dumps({"architecture": "amd64", "os": "linux", "made-of": texts}).encode()


async def push_blob(client, headers, image: str, data: bytes, repository: str = "images") -> str:
    """Upload a blob the way Docker does: begin, one chunk, complete. Returns its digest."""
    begun = await client.post(f"/v2/{repository}/{image}/blobs/uploads/", headers=headers)
    assert begun.status_code == 202, begun.text
    sent = await client.patch(begun.headers["Location"], content=data, headers=headers)
    assert sent.status_code == 202, sent.text
    digest = digest_of(data)
    done = await client.put(f"{sent.headers['Location']}?digest={digest}", headers=headers)
    assert done.status_code == 201, done.text
    return digest


async def push_manifest(
    client, headers, image: str, reference: str, manifest: bytes, repository: str = "images"
):
    """Put a manifest as it is, by tag or by digest. Returns the response."""
    declared = json.loads(manifest).get("mediaType", OCI_MANIFEST)
    return await client.put(
        f"/v2/{repository}/{image}/manifests/{reference}",
        content=manifest,
        headers={**headers, "Content-Type": declared},
    )


async def push_image(
    client, headers, image: str, tag: str, *texts: str, repository: str = "images"
) -> bytes:
    """Push an image whose layers hold these texts, under a tag. Returns its manifest."""
    config = config_for(*texts)
    layers = [layer(text) for text in texts]
    for data in (config, *layers):
        await push_blob(client, headers, image, data, repository)
    manifest = image_manifest(config, *layers)
    response = await push_manifest(client, headers, image, tag, manifest, repository)
    assert response.status_code == 201, response.text
    return manifest


def error_code(response) -> str:
    """The registry's code for an error answer."""
    return response.json()["errors"][0]["code"]


@pytest.fixture
async def images(db) -> Repository:
    return await create(db, "images")


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

`backend/tests/repositories/docker/test_registry.py`:

```python
import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.security import roles, users
from megooarti.security.models import LoginFailure
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer
from tests.repositories.docker.conftest import V2, error_code, push_image

CHALLENGE = 'Bearer realm="https://test/v2/token",service="test"'


async def sign_in(client, headers: dict | None = None) -> dict[str, str]:
    """Do what `docker login` does. Returns the header to send from then on."""
    response = await client.get("/v2/token", params={"service": "test"}, headers=headers or {})
    assert response.status_code == 200, response.text
    return bearer(response.json()["token"])


async def let_anyone(db, *permissions: str) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    await roles.create_role(db, "public", "", list(permissions), [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await db.commit()


async def test_a_request_without_credentials_is_told_how_to_sign_in(client, images):
    base = await client.get("/v2/")
    pull = await client.get(f"{V2}/app/manifests/latest")
    push = await client.post(f"{V2}/team/app/blobs/uploads/")

    for response in (base, pull, push):
        assert (response.status_code, error_code(response)) == (401, "UNAUTHORIZED")
        assert response.headers["Docker-Distribution-Api-Version"] == "registry/2.0"
    assert base.headers["WWW-Authenticate"] == CHALLENGE
    assert pull.headers["WWW-Authenticate"] == f'{CHALLENGE},scope="repository:images/app:pull"'
    assert push.headers["WWW-Authenticate"] == (
        f'{CHALLENGE},scope="repository:images/team/app:pull,push"'
    )


async def test_the_challenge_names_the_public_address(client, images, db):
    await set_setting(db, "base_url", "https://registry.example/")
    await db.commit()

    response = await client.get("/v2/")

    assert response.headers["WWW-Authenticate"].startswith(
        'Bearer realm="https://registry.example/v2/token",'
    )


async def test_signing_in_gives_a_token_that_the_registry_takes(client, images, make_user):
    await make_user("root", roles=["admin"])

    response = await client.get("/v2/token", headers=basic("root", PASSWORD))
    token = bearer(response.json()["token"])
    base = await client.get("/v2/", headers=token)

    assert response.json()["token"] == response.json()["access_token"]
    assert response.json()["expires_in"] == 300
    assert response.headers["Cache-Control"] == "no-store"
    assert (base.status_code, base.json()) == (200, {})
    assert base.headers["Docker-Distribution-Api-Version"] == "registry/2.0"


async def test_an_api_token_signs_in_too(client, images, make_user, make_token):
    owner = await make_user("root", roles=["admin"])
    api_token = await make_token(owner)

    for credentials in (basic("root", api_token), basic("__token__", api_token), bearer(api_token)):
        token = await sign_in(client, credentials)
        assert (await client.get("/v2/", headers=token)).status_code == 200


async def test_credentials_sent_with_the_request_itself_are_taken(
    client, images, root, make_token, db
):
    api_token = await make_token(await users.get_user_by_username(db, "root"))

    for credentials in (root, bearer(api_token)):
        assert (await client.get("/v2/", headers=credentials)).status_code == 200


async def test_wrong_credentials_get_no_token_and_are_counted(client, images, make_user, db):
    await make_user("root", roles=["admin"])

    response = await client.get("/v2/token", headers=basic("root", "not the password"))

    assert (response.status_code, error_code(response)) == (401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'
    assert await db.scalar(select(LoginFailure.count).where(LoginFailure.subject == "user:root"))


async def test_too_many_wrong_sign_ins_are_slowed_down(client, images, make_user):
    await make_user("root", roles=["admin"])
    for _ in range(5):
        await client.get("/v2/token", headers=basic("root", "a guess"))

    response = await client.get("/v2/token", headers=basic("root", "another guess"))

    assert (response.status_code, error_code(response)) == (429, "TOOMANYREQUESTS")
    assert "Retry-After" in response.headers


async def test_a_token_that_is_not_ours_is_refused_with_the_challenge(client, images):
    for value in ("mgr_made-up", "mga_" + "x" * 43, "anything"):
        response = await client.get("/v2/", headers=bearer(value))
        assert (response.status_code, error_code(response)) == (401, "UNAUTHORIZED")
        assert response.headers["WWW-Authenticate"] == CHALLENGE


async def test_nobody_gets_a_token_unless_anyone_may_read(client, images, root, db):
    await push_image(client, root, "app", "latest", "one")
    refused = await client.get("/v2/token")
    await let_anyone(db, "repository:docker:images:read")

    token = await sign_in(client)
    base = await client.get("/v2/", headers=token)
    pulled = await client.get(f"{V2}/app/manifests/latest", headers=token)
    pushed = await client.post(f"{V2}/app/blobs/uploads/", headers=token)

    assert (refused.status_code, error_code(refused)) == (401, "UNAUTHORIZED")
    assert (base.status_code, pulled.status_code) == (200, 200)
    # Not signed in: asked to, so that the client prompts for credentials.
    assert (pushed.status_code, error_code(pushed)) == (401, "UNAUTHORIZED")
    assert pushed.headers["WWW-Authenticate"].startswith("Bearer ")


async def test_anonymous_access_does_not_spare_a_request_the_challenge(client, images, db):
    await let_anyone(db, "repository:docker:images:read")

    response = await client.get(f"{V2}/app/manifests/latest")

    assert response.status_code == 401  # a client then fetches a token, and learns it may read


async def test_reading_needs_read_and_a_signed_in_caller_is_denied_not_challenged(
    client, images, root, make_user, db
):
    await push_image(client, root, "app", "latest", "one")
    await roles.create_role(db, "readers", "", ["repository:docker:images:read"], [])
    await db.commit()
    await make_user("reader", roles=["readers"])
    await make_user("stranger")
    reader = await sign_in(client, basic("reader", PASSWORD))
    stranger = await sign_in(client, basic("stranger", PASSWORD))

    allowed = await client.get(f"{V2}/app/manifests/latest", headers=reader)
    denied = await client.get(f"{V2}/app/manifests/latest", headers=stranger)
    push = await client.post(f"{V2}/app/blobs/uploads/", headers=reader)

    assert allowed.status_code == 200
    for response in (denied, push):
        assert (response.status_code, error_code(response)) == (403, "DENIED")
        assert "WWW-Authenticate" not in response.headers


async def test_a_repository_that_is_not_a_registry_is_unknown_here(client, files, images, root):
    not_docker = await client.get("/v2/files/app/manifests/latest", headers=root)
    missing = await client.get("/v2/no-such-repository/app/manifests/latest", headers=root)
    under_repository = await client.get("/repository/images/app/manifests/latest", headers=root)

    for response in (not_docker, missing):
        assert (response.status_code, error_code(response)) == (404, "NAME_UNKNOWN")
    # And a registry is not served where the other formats are.
    assert under_repository.status_code == 404
    assert under_repository.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "path",
    ["app", "app/manifests", "App/manifests/latest", "app/blobs/latest", "app/tags", "x/y/z"],
)
async def test_an_address_that_means_nothing_is_unknown(client, images, root, path):
    response = await client.get(f"{V2}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "NAME_UNKNOWN")


async def test_an_image_name_has_a_limit_with_its_repository(client, images, root):
    long_name = "/".join(["a" * 60] * 4)  # 243 characters, and "images/" before it

    fits = await client.get(f"/v2/images/{long_name}/tags/list", headers=root)
    too_long = await client.get(f"/v2/images/{long_name}/aaaaaa/tags/list", headers=root)

    assert (fits.status_code, error_code(fits)) == (404, "NAME_UNKNOWN")  # no such image
    assert (too_long.status_code, error_code(too_long)) == (400, "NAME_INVALID")


async def test_an_offline_repository_is_unavailable(client, images, root, db):
    repository = await service.get_repository(db, "images")
    repository.online = False
    await db.commit()

    response = await client.get(f"{V2}/app/manifests/latest", headers=root)

    assert (response.status_code, error_code(response)) == (503, "UNKNOWN")


async def test_the_referrers_api_is_not_there(client, images, root):
    response = await client.get(f"{V2}/app/referrers/sha256:{'a' * 64}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "UNSUPPORTED")


async def test_a_format_can_only_be_hosted_for_now(admin_client):
    for kind, extra in (
        ("proxy", {"proxy": {"remote_url": "https://registry-1.docker.io"}}),
        ("group", {"group": {"members": []}}),
    ):
        body = {"name": f"docker-{kind}", "format": "docker", "type": kind, **extra}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == 422, kind
```

`backend/tests/repositories/docker/test_push.py`:

```python
import hashlib

import pytest
from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Upload
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import V2, create, digest_of, error_code, layer, push_blob

LAYER = layer("one") * 500  # 12,500 bytes
DIGEST = digest_of(LAYER)
UPLOADS = f"{V2}/team/app/blobs/uploads/"
BLOB = f"{V2}/team/app/blobs/{DIGEST}"


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def temporary_files(settings) -> list[str]:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return [path.name for path in directory.iterdir()] if directory.exists() else []


async def test_a_layer_is_pushed_as_docker_pushes_it(client, images, root, db, settings):
    missing = await client.head(BLOB, headers=root)
    begun = await client.post(UPLOADS, headers=root)
    upload = begun.headers["Docker-Upload-UUID"]
    sent = await client.patch(begun.headers["Location"], content=LAYER, headers=root)
    done = await client.put(f"{sent.headers['Location']}?digest={DIGEST}", headers=root)
    found = await client.head(BLOB, headers=root)
    fetched = await client.get(BLOB, headers=root)

    assert (missing.status_code, missing.content) == (404, b"")
    assert begun.status_code == 202
    assert begun.headers["Location"] == f"{UPLOADS}{upload}"
    assert (begun.headers["Range"], len(upload)) == ("0-0", 32)
    assert (sent.status_code, sent.headers["Range"]) == (202, f"0-{len(LAYER) - 1}")
    assert sent.headers["Docker-Upload-UUID"] == upload
    assert (done.status_code, done.content) == (201, b"")
    assert done.headers["Location"] == BLOB
    assert done.headers["Docker-Content-Digest"] == DIGEST
    assert (found.status_code, found.headers["Content-Length"]) == (200, str(len(LAYER)))
    assert found.headers["Docker-Content-Digest"] == DIGEST
    assert (fetched.content, fetched.headers["Content-Type"]) == (LAYER, "application/octet-stream")
    assert fetched.headers["Docker-Distribution-Api-Version"] == "registry/2.0"
    assert list(await db.scalars(select(Asset.path))) == [f"blobs/{DIGEST}"]
    assert await count(db, Upload) == 0
    assert temporary_files(settings) == []


async def test_a_layer_is_shared_by_every_image_of_the_repository(client, images, root):
    await push_blob(client, root, "team/app", LAYER)

    elsewhere = await client.get(f"{V2}/another/image/blobs/{DIGEST}", headers=root)
    ranged = await client.get(BLOB, headers={**root, "Range": "bytes=0-9"})

    assert elsewhere.content == LAYER
    assert (ranged.status_code, ranged.content) == (206, LAYER[:10])


async def test_a_layer_can_arrive_in_chunks_and_be_resumed(client, images, root):
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]

    first = await client.patch(
        location, content=LAYER[:5000], headers={**root, "Content-Range": "0-4999"}
    )
    asked = await client.get(location, headers=root)
    again = await client.patch(
        location, content=LAYER[:5000], headers={**root, "Content-Range": "0-4999"}
    )
    second = await client.patch(
        location, content=LAYER[5000:9000], headers={**root, "Content-Range": "5000-8999"}
    )
    # The last chunk may come with the request that completes the upload.
    done = await client.put(f"{location}?digest={DIGEST}", content=LAYER[9000:], headers=root)

    assert (first.status_code, first.headers["Range"]) == (202, "0-4999")
    assert (asked.status_code, asked.headers["Range"]) == (204, "0-4999")
    assert (again.status_code, error_code(again)) == (416, "BLOB_UPLOAD_INVALID")
    assert again.headers["Range"] == "0-4999"  # where to go on from
    assert second.headers["Range"] == "0-8999"
    assert done.status_code == 201
    assert (await client.get(BLOB, headers=root)).content == LAYER


async def test_a_whole_layer_in_one_request(client, images, root):
    at_once = await client.post(f"{UPLOADS}?digest={DIGEST}", content=LAYER, headers=root)
    begun = await client.post(UPLOADS, headers=root)
    with_the_last = await client.put(
        f"{begun.headers['Location']}?digest={DIGEST}", content=LAYER, headers=root
    )

    assert (at_once.status_code, at_once.headers["Location"]) == (201, BLOB)
    assert with_the_last.status_code == 201  # here already: nothing new is stored
    assert (await client.get(BLOB, headers=root)).content == LAYER


async def test_a_layer_that_is_here_is_mounted_not_uploaded(client, images, root, db):
    await push_blob(client, root, "team/app", LAYER)
    other = digest_of(b"not here")

    mounted = await client.post(
        f"{V2}/another/image/blobs/uploads/",
        params={"mount": DIGEST, "from": "images/team/app"},
        headers=root,
    )
    not_here = await client.post(UPLOADS, params={"mount": other, "from": "x/y"}, headers=root)

    assert mounted.status_code == 201
    assert mounted.headers["Location"] == f"{V2}/another/image/blobs/{DIGEST}"
    assert mounted.headers["Docker-Content-Digest"] == DIGEST
    assert (not_here.status_code, "Docker-Upload-UUID" in not_here.headers) == (202, True)


async def test_content_that_is_not_what_its_digest_says_is_refused(
    client, images, root, db, settings
):
    wrong = digest_of(b"something else")
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]
    await client.patch(location, content=LAYER, headers=root)

    finished = await client.put(f"{location}?digest={wrong}", headers=root)
    after = await client.get(location, headers=root)
    at_once = await client.post(f"{UPLOADS}?digest={wrong}", content=LAYER, headers=root)

    for response in (finished, at_once):
        assert (response.status_code, error_code(response)) == (400, "DIGEST_INVALID")
    assert (after.status_code, error_code(after)) == (404, "BLOB_UPLOAD_UNKNOWN")  # it is over
    assert await count(db, Asset) == 0
    assert temporary_files(settings) == []


@pytest.mark.parametrize(
    "digest",
    ["", "latest", "sha256:" + "A" * 64, "sha512:" + "a" * 128, "sha256:" + "a" * 63],
)
async def test_only_a_sha256_digest_completes_an_upload(client, images, root, digest):
    begun = await client.post(UPLOADS, headers=root)
    await client.patch(begun.headers["Location"], content=LAYER, headers=root)

    response = await client.put(begun.headers["Location"], params={"digest": digest}, headers=root)
    missing = await client.put(begun.headers["Location"], headers=root)

    for refused in (response, missing):
        assert (refused.status_code, error_code(refused)) == (400, "DIGEST_INVALID")
    still = await client.get(begun.headers["Location"], headers=root)
    assert still.headers["Range"] == f"0-{len(LAYER) - 1}"  # the upload can still be completed


async def test_an_abandoned_upload_is_gone(client, images, root, db, settings):
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]
    await client.patch(location, content=LAYER, headers=root)

    abandoned = await client.delete(location, headers=root)
    again = await client.delete(location, headers=root)
    more = await client.patch(location, content=b"more", headers=root)

    assert abandoned.status_code == 204
    for response in (again, more):
        assert (response.status_code, error_code(response)) == (404, "BLOB_UPLOAD_UNKNOWN")
    assert await count(db, Upload) == 0
    assert temporary_files(settings) == []


async def test_an_upload_belongs_to_the_image_it_was_begun_for(client, images, root, db):
    await create(db, "others")
    begun = await client.post(UPLOADS, headers=root)
    upload = begun.headers["Docker-Upload-UUID"]

    for address in (
        f"{V2}/another/app/blobs/uploads/{upload}",
        f"/v2/others/team/app/blobs/uploads/{upload}",
        f"{UPLOADS}{'0' * 32}",
    ):
        response = await client.patch(address, content=b"x", headers=root)
        assert (response.status_code, error_code(response)) == (404, "BLOB_UPLOAD_UNKNOWN")


async def test_a_bad_content_range_is_refused(client, images, root):
    begun = await client.post(UPLOADS, headers=root)

    response = await client.patch(
        begun.headers["Location"], content=b"x", headers={**root, "Content-Range": "start-end"}
    )

    assert (response.status_code, error_code(response)) == (400, "BLOB_UPLOAD_INVALID")


async def test_pushing_needs_the_right_to_add(client, images, root, make_user, db):
    await push_blob(client, root, "team/app", LAYER)
    await roles.create_role(db, "readers", "", ["repository:docker:images:read"], [])
    await db.commit()
    await make_user("reader", roles=["readers"])
    reader = basic("reader", PASSWORD)
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]

    attempts = [
        await client.post(UPLOADS, headers=reader),
        await client.post(f"{UPLOADS}?digest={DIGEST}", content=LAYER, headers=reader),
        await client.post(UPLOADS, params={"mount": DIGEST, "from": "x"}, headers=reader),
        await client.patch(location, content=b"x", headers=reader),
        await client.get(location, headers=reader),
        await client.put(f"{location}?digest={DIGEST}", headers=reader),
        await client.delete(location, headers=reader),
    ]

    for response in attempts:
        assert (response.status_code, error_code(response)) == (403, "DENIED")
    assert (await client.get(BLOB, headers=reader)).content == LAYER  # reading is allowed
    assert (await client.get(location, headers=root)).headers["Range"] == "0-0"  # untouched


async def test_a_read_only_repository_takes_no_uploads(client, db, root):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await client.post("/v2/frozen/app/blobs/uploads/", headers=root)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "allow"),
    [
        ("DELETE", f"team/app/blobs/{DIGEST}", "GET, HEAD"),
        ("PUT", f"team/app/blobs/{DIGEST}", "GET, HEAD"),
        ("GET", "team/app/blobs/uploads/", "POST"),
        ("POST", "team/app/blobs/uploads/" + "0" * 32, "GET, PATCH, PUT, DELETE"),
    ],
)
async def test_what_an_address_does_not_do(client, images, root, method, path, allow):
    response = await client.request(method, f"{V2}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
    assert response.headers["Allow"] == allow


async def test_a_large_layer_arrives_whole_without_being_copied(client, images, root, settings):
    data = bytes(range(256)) * 4096 * 3  # 3 MiB, sent in many pieces
    digest = digest_of(data)

    async def pieces():
        for start in range(0, len(data), 65_521):
            yield data[start : start + 65_521]

    begun = await client.post(UPLOADS, headers=root)
    sent = await client.patch(begun.headers["Location"], content=pieces(), headers=root)
    done = await client.put(f"{begun.headers['Location']}?digest={digest}", headers=root)
    fetched = await client.get(f"{V2}/team/app/blobs/{digest}", headers=root)

    assert (sent.headers["Range"], done.status_code) == (f"0-{len(data) - 1}", 201)
    assert hashlib.sha256(fetched.content).hexdigest() == hashlib.sha256(data).hexdigest()
    assert temporary_files(settings) == []
```

`backend/tests/repositories/docker/test_images.py`:

```python
import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from megooarti.clock import utcnow
from megooarti.repositories import upkeep
from megooarti.repositories.docker.manifests import (
    DOCKER_LIST,
    DOCKER_MANIFEST,
    OCI_INDEX,
    OCI_MANIFEST,
)
from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import (
    V2,
    config_for,
    create,
    digest_of,
    error_code,
    image_manifest,
    index_manifest,
    layer,
    push_blob,
    push_image,
    push_manifest,
)

CONFIG = b'{"architecture": "amd64", "os": "linux"}'


async def stored(db) -> list[str]:
    return list(await db.scalars(select(Asset.path).order_by(Asset.path)))


async def blobs_stored(db) -> int:
    return len([path for path in await stored(db) if path.startswith("blobs/")])


async def test_an_image_is_pushed_and_pulled_by_tag_and_by_digest(client, images, root, db):
    manifest = await push_image(client, root, "team/app", "1.0", "base", "code")
    digest = digest_of(manifest)

    by_tag = await client.get(f"{V2}/team/app/manifests/1.0", headers=root)
    by_digest = await client.get(f"{V2}/team/app/manifests/{digest}", headers=root)
    headed = await client.head(f"{V2}/team/app/manifests/1.0", headers=root)

    for response in (by_tag, by_digest):
        assert (response.status_code, response.content) == (200, manifest)
        assert response.headers["Content-Type"] == OCI_MANIFEST
        assert response.headers["Docker-Content-Digest"] == digest
    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Docker-Content-Digest"] == digest
    assert headed.headers["Content-Length"] == str(len(manifest))
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "team/app", "1.0")
    assert f"manifests/team/app/{digest}" in await stored(db)
    assert "tags/team/app/1.0" in await stored(db)


async def test_pushing_a_manifest_answers_where_it_is(client, images, root):
    for data in (CONFIG, layer("one")):
        await push_blob(client, root, "app", data)
    manifest = image_manifest(CONFIG, layer("one"))

    response = await push_manifest(client, root, "app", "latest", manifest)

    assert (response.status_code, response.content) == (201, b"")
    assert response.headers["Location"] == f"{V2}/app/manifests/{digest_of(manifest)}"
    assert response.headers["Docker-Content-Digest"] == digest_of(manifest)


@pytest.mark.parametrize("media_type", [OCI_MANIFEST, DOCKER_MANIFEST])
async def test_both_kinds_of_image_manifest_are_served_as_they_were_pushed(
    client, images, root, media_type
):
    for data in (CONFIG, layer("one")):
        await push_blob(client, root, "app", data)
    manifest = image_manifest(CONFIG, layer("one"), media_type=media_type)

    await push_manifest(client, root, "app", "latest", manifest)
    pulled = await client.get(f"{V2}/app/manifests/latest", headers=root)

    assert (pulled.content, pulled.headers["Content-Type"]) == (manifest, media_type)


@pytest.mark.parametrize("media_type", [OCI_INDEX, DOCKER_LIST])
async def test_an_image_for_several_platforms_is_one_image(client, images, root, media_type):
    amd64 = await push_image(client, root, "app", "amd64-only", "amd64 code")
    arm64 = await push_image(client, root, "app", "arm64-only", "arm64 code")
    index = index_manifest(amd64, arm64, media_type=media_type)

    pushed = await push_manifest(client, root, "app", "1.0", index)
    pulled = await client.get(f"{V2}/app/manifests/1.0", headers=root)
    platform = await client.get(f"{V2}/app/manifests/{digest_of(arm64)}", headers=root)

    assert pushed.status_code == 201
    assert (pulled.content, pulled.headers["Content-Type"]) == (index, media_type)
    assert platform.content == arm64


async def test_a_manifest_must_refer_to_what_has_been_pushed(client, images, root, db):
    await push_blob(client, root, "app", CONFIG)
    missing_layer = image_manifest(CONFIG, layer("never pushed"))
    platform = await push_image(client, root, "other", "latest", "one")
    missing_platform = index_manifest(platform)  # pushed, but under another image

    for manifest, missing in ((missing_layer, layer("never pushed")), (missing_platform, platform)):
        response = await push_manifest(client, root, "app", "latest", manifest)
        assert (response.status_code, error_code(response)) == (400, "MANIFEST_BLOB_UNKNOWN")
        assert response.json()["errors"][0]["detail"] == [digest_of(missing)]
    assert not [path for path in await stored(db) if path.startswith(("manifests/app", "tags/app"))]


async def test_a_layer_kept_elsewhere_need_not_be_pushed(client, images, root):
    await push_blob(client, root, "app", CONFIG)
    document = json.loads(image_manifest(CONFIG, layer("foreign")))
    document["layers"][0]["urls"] = ["https://elsewhere.example/layer"]

    response = await push_manifest(client, root, "app", "latest", json.dumps(document).encode())

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"not json", OCI_MANIFEST),
        (b"{}", OCI_MANIFEST),
        (b'{"schemaVersion": 1}', "application/vnd.docker.distribution.manifest.v1+prettyjws"),
        (image_manifest(CONFIG), DOCKER_MANIFEST),  # says OCI inside
        (b" " * (4 * 1024 * 1024 + 1), OCI_MANIFEST),
    ],
    ids=["not-json", "empty", "schema-1", "two-types", "too-large"],
)
async def test_what_is_not_a_manifest_is_refused(client, images, root, db, body, content_type):
    response = await client.put(
        f"{V2}/app/manifests/latest", content=body, headers={**root, "Content-Type": content_type}
    )

    assert (response.status_code, error_code(response)) == (400, "MANIFEST_INVALID")
    assert await stored(db) == []


async def test_a_manifest_pushed_by_digest_must_be_that_manifest(client, images, root):
    for data in (CONFIG, layer("one")):
        await push_blob(client, root, "app", data)
    manifest = image_manifest(CONFIG, layer("one"))

    wrong = await push_manifest(client, root, "app", "sha256:" + "0" * 64, manifest)
    right = await push_manifest(client, root, "app", digest_of(manifest), manifest)
    untagged = await client.get(f"{V2}/app/tags/list", headers=root)

    assert (wrong.status_code, error_code(wrong)) == (400, "DIGEST_INVALID")
    assert right.status_code == 201
    assert (untagged.status_code, error_code(untagged)) == (404, "NAME_UNKNOWN")  # no tag yet


async def test_a_tag_moves_unless_the_repository_says_tags_stay(client, db, root):
    await create(db, "images")
    await create(db, "releases", hosted={"deployment_policy": "disable_redeploy"})
    for repository in ("images", "releases"):
        first = await push_image(client, root, "app", "1.0", "first", repository=repository)

    second = await push_image(client, root, "app", "1.0", "second")
    moved = await client.get(f"{V2}/app/manifests/1.0", headers=root)
    old = await client.get(f"{V2}/app/manifests/{digest_of(first)}", headers=root)
    for data in (config_for("second"), layer("second")):
        await push_blob(client, root, "app", data, "releases")
    refused = await push_manifest(client, root, "app", "1.0", second, "releases")
    again = await push_manifest(client, root, "app", "1.0", first, "releases")
    other_tag = await push_manifest(client, root, "app", "1.1", second, "releases")

    assert moved.content == second
    assert old.content == first  # what the tag named before can still be pulled by digest
    assert (refused.status_code, error_code(refused)) == (409, "DENIED")
    assert again.status_code == 201  # the same image under the same tag changes nothing
    assert other_tag.status_code == 201


async def test_each_change_needs_its_own_permission(client, images, root, make_user, db):
    for action in ("add", "edit", "delete"):
        permissions = [f"repository:docker:images:{action}", "repository:docker:images:read"]
        await roles.create_role(db, f"may-{action}", "", permissions, [])
    await db.commit()
    for action in ("add", "edit", "delete"):
        await make_user(f"{action}er", roles=[f"may-{action}"])
    adder, editor, deleter = (
        basic(f"{action}er", PASSWORD) for action in ("add", "edit", "delete")
    )
    first = await push_image(client, adder, "app", "1.0", "first")
    second = await push_image(client, adder, "app", "2.0", "second")

    add_again = await push_manifest(client, adder, "app", "1.0", first)
    add_moves = await push_manifest(client, adder, "app", "1.0", second)
    edit_moves = await push_manifest(client, editor, "app", "1.0", second)
    edit_new = await push_manifest(client, editor, "app", "3.0", second)
    edit_deletes = await client.delete(f"{V2}/app/manifests/2.0", headers=editor)
    delete_pushes = await client.post(f"{V2}/app/blobs/uploads/", headers=deleter)
    delete_deletes = await client.delete(f"{V2}/app/manifests/2.0", headers=deleter)

    assert (add_again.status_code, edit_moves.status_code, delete_deletes.status_code) == (
        201,
        201,
        202,
    )
    for response in (add_moves, edit_new, edit_deletes, delete_pushes):
        assert (response.status_code, error_code(response)) == (403, "DENIED")


async def test_the_tags_of_an_image_are_listed_in_order_a_page_at_a_time(client, images, root):
    for tag in ("1.10", "1.2", "latest", "1.9"):
        await push_image(client, root, "team/app", tag, "one")

    everything = await client.get(f"{V2}/team/app/tags/list", headers=root)
    first = await client.get(f"{V2}/team/app/tags/list", params={"n": 2}, headers=root)
    rest = await client.get(first.headers["Link"].split(">")[0].lstrip("<"), headers=root)
    unknown = await client.get(f"{V2}/no/such/image/tags/list", headers=root)

    assert everything.json() == {
        "name": "images/team/app",
        "tags": ["1.10", "1.2", "1.9", "latest"],
    }
    assert "Link" not in everything.headers
    assert first.json()["tags"] == ["1.10", "1.2"]
    assert first.headers["Link"] == (f'<{V2}/team/app/tags/list?n=2&last=1.2>; rel="next"')
    assert (rest.json()["tags"], "Link" in rest.headers) == (["1.9", "latest"], False)
    assert (unknown.status_code, error_code(unknown)) == (404, "NAME_UNKNOWN")


async def test_the_catalog_lists_the_images_a_caller_may_read(client, db, root, make_user):
    await create(db, "images")
    await create(db, "private")
    await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "base", "1.0", "one")
    await push_image(client, root, "secret", "1.0", "one", repository="private")
    await push_blob(client, root, "never/tagged", layer("only a layer"))
    await roles.create_role(db, "readers", "", ["repository:docker:images:read"], [])
    await db.commit()
    await make_user("reader", roles=["readers"])

    everything = await client.get("/v2/_catalog", headers=root)
    limited = await client.get("/v2/_catalog", headers=basic("reader", PASSWORD))
    first = await client.get("/v2/_catalog", params={"n": 2}, headers=root)
    rest = await client.get(first.headers["Link"].split(">")[0].lstrip("<"), headers=root)
    without = await client.get("/v2/_catalog")

    assert everything.json() == {
        "repositories": ["images/base", "images/team/app", "private/secret"]
    }
    assert limited.json() == {"repositories": ["images/base", "images/team/app"]}
    assert first.json() == {"repositories": ["images/base", "images/team/app"]}
    assert first.headers["Link"] == '</v2/_catalog?n=2&last=images/team/app>; rel="next"'
    assert rest.json() == {"repositories": ["private/secret"]}
    assert (without.status_code, error_code(without)) == (401, "UNAUTHORIZED")


async def test_deleting_an_image_removes_what_only_it_used(client, images, root, db):
    kept = await push_image(client, root, "app", "1.0", "base", "code v1")
    gone = await push_image(client, root, "app", "2.0", "base", "code v2")
    await push_manifest(client, root, "app", "latest", gone)
    before = await blobs_stored(db)

    removed = await client.delete(f"{V2}/app/manifests/{digest_of(gone)}", headers=root)
    again = await client.delete(f"{V2}/app/manifests/{digest_of(gone)}", headers=root)

    assert (removed.status_code, before) == (202, 5)  # two configurations, three layers
    assert (again.status_code, error_code(again)) == (404, "MANIFEST_UNKNOWN")
    assert await stored(db) == sorted(
        [
            f"blobs/{digest_of(layer('base'))}",  # the other image uses it
            f"blobs/{digest_of(layer('code v1'))}",
            f"blobs/{digest_of(config_for('base', 'code v1'))}",
            f"manifests/app/{digest_of(kept)}",
            "tags/app/1.0",
        ]
    )
    for tag in ("2.0", "latest"):
        response = await client.get(f"{V2}/app/manifests/{tag}", headers=root)
        assert (response.status_code, error_code(response)) == (404, "MANIFEST_UNKNOWN")
    assert (await client.get(f"{V2}/app/manifests/1.0", headers=root)).content == kept


async def test_deleting_a_tag_removes_nothing_else(client, images, root, db):
    manifest = await push_image(client, root, "app", "1.0", "one")
    before = await stored(db)

    removed = await client.delete(f"{V2}/app/manifests/1.0", headers=root)
    again = await client.delete(f"{V2}/app/manifests/1.0", headers=root)
    pinned = await client.get(f"{V2}/app/manifests/{digest_of(manifest)}", headers=root)

    assert removed.status_code == 202
    assert (again.status_code, error_code(again)) == (404, "MANIFEST_UNKNOWN")
    assert pinned.content == manifest  # a deployment may have pinned it by its digest
    assert await stored(db) == [path for path in before if path != "tags/app/1.0"]


async def test_deleting_an_image_for_several_platforms_removes_its_platforms(
    client, images, root, db
):
    amd64 = await push_image(client, root, "app", "amd64", "shared", "amd64 code")
    arm64 = await push_image(client, root, "app", "scratch", "shared", "arm64 code")
    await client.delete(f"{V2}/app/manifests/scratch", headers=root)  # arm64 has no tag now
    index = index_manifest(amd64, arm64)
    await push_manifest(client, root, "app", "1.0", index)

    removed = await client.delete(f"{V2}/app/manifests/{digest_of(index)}", headers=root)

    assert removed.status_code == 202
    remaining = await stored(db)
    # The platform with a tag of its own stays whole; the other went with the index.
    assert f"manifests/app/{digest_of(amd64)}" in remaining
    assert f"manifests/app/{digest_of(arm64)}" not in remaining
    assert f"blobs/{digest_of(layer('shared'))}" in remaining
    assert f"blobs/{digest_of(layer('amd64 code'))}" in remaining
    assert f"blobs/{digest_of(layer('arm64 code'))}" not in remaining
    assert "tags/app/1.0" not in remaining and "tags/app/amd64" in remaining


async def test_the_same_manifest_under_two_images_keeps_its_layers_until_both_go(
    client, images, root, db
):
    manifest = await push_image(client, root, "one", "1.0", "shared")
    await push_manifest(client, root, "two", "1.0", manifest)

    await client.delete(f"/v2/images/one/manifests/{digest_of(manifest)}", headers=root)
    still = await blobs_stored(db)
    pulled = await client.get("/v2/images/two/manifests/1.0", headers=root)
    await client.delete(f"/v2/images/two/manifests/{digest_of(manifest)}", headers=root)

    assert (still, pulled.content) == (2, manifest)
    assert await stored(db) == []


async def test_maintenance_removes_blobs_no_manifest_has_used_for_a_day(
    client, images, root, db, sessionmaker, settings
):
    await push_image(client, root, "app", "1.0", "used")
    await push_blob(client, root, "app", layer("abandoned push"))
    await push_blob(client, root, "app", layer("pushed just now"))
    old = [f"blobs/{digest_of(layer(text))}" for text in ("used", "abandoned push")]
    await db.execute(
        update(Asset).where(Asset.path.in_(old)).values(updated_at=utcnow() - timedelta(days=2))
    )
    await db.commit()

    await upkeep.run(sessionmaker, settings, utcnow())

    remaining = await stored(db)
    assert f"blobs/{digest_of(layer('abandoned push'))}" not in remaining
    assert f"blobs/{digest_of(layer('used'))}" in remaining
    assert f"blobs/{digest_of(layer('pushed just now'))}" in remaining  # a push may be under way
    assert (await client.get(f"{V2}/app/manifests/1.0", headers=root)).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "app/manifests/latest"),
        ("PATCH", "app/manifests/latest"),
        ("POST", "app/tags/list"),
    ],
)
async def test_what_a_manifest_or_a_tag_list_does_not_do(client, images, root, method, path):
    response = await client.request(method, f"{V2}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
```

`backend/tests/repositories/docker/test_races.py`:

```python
"""A push and a delete at the same moment, which only real transactions can show."""

import asyncio

import pytest
from starlette.requests import Request

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.docker import names
from megooarti.repositories.docker.errors import RegistryError
from megooarti.repositories.docker.format import _manifest
from megooarti.repositories.docker.manifests import OCI_MANIFEST
from megooarti.repositories.models import Repository
from tests.repositories.conftest import someone
from tests.repositories.docker.conftest import digest_of, image_manifest, layer
from tests.storage.test_races import Factory, run

PUSHER = someone("repository:docker:images")
SHARED = layer("shared by both images")
OLD = image_manifest(b'{"image": "old"}', SHARED)
NEW = image_manifest(b'{"image": "new"}', SHARED)


def request(method: str, body: bytes = b"") -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", OCI_MANIFEST.encode())]
    scope = {"type": "http", "method": method, "path": "/", "query_string": b"", "headers": headers}
    return Request(scope, receive)


async def context_in(db, settings: Settings, repository: Repository) -> RepositoryContext:
    return await build_context(db, settings, repository, PUSHER)


async def prepare(factory: Factory, settings: Settings) -> Repository:
    """A repository with the old image pushed, and the new one's blobs but not its manifest."""
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="images",
            format="docker",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        await db.commit()
        context = await context_in(db, settings, repository)
        for data in (SHARED, b'{"image": "old"}', b'{"image": "new"}'):
            await context.store(names.blob_path(digest_of(data)), await context.stage_bytes(data))
        await db.commit()
        await push(context, "old", OLD)
        await db.commit()
        return repository


async def push(context: RepositoryContext, image: str, manifest: bytes) -> None:
    parsed = names.DockerPath("manifest", image, "latest")
    await _manifest(context, request("PUT", manifest), parsed)


async def delete(context: RepositoryContext, image: str, manifest: bytes) -> None:
    parsed = names.DockerPath("manifest", image, digest_of(manifest))
    await _manifest(context, request("DELETE"), parsed)


async def state(factory: Factory, settings: Settings, repository: Repository) -> set[str]:
    async with factory() as db:
        context = await context_in(db, settings, repository)
        asked = [
            names.blob_path(digest_of(SHARED)),
            names.manifest_path("new", digest_of(NEW)),
            names.manifest_path("old", digest_of(OLD)),
        ]
        return {
            path.split("/")[0] + ":" + path.split("/")[1][:3]
            for path in await context.present(asked)
        }


def test_a_push_that_comes_first_keeps_the_layer_a_delete_would_have_removed(
    empty_database, tmp_path
):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await prepare(factory, settings)

        async def pushing() -> None:
            async with factory() as db:
                await push(await context_in(db, settings, repository), "new", NEW)
                await asyncio.sleep(0.3)  # stay open while the delete arrives
                await db.commit()

        async def deleting() -> None:
            await asyncio.sleep(0.1)
            async with factory() as db:
                await delete(await context_in(db, settings, repository), "old", OLD)
                await db.commit()

        await asyncio.gather(pushing(), deleting())

        assert await state(factory, settings, repository) == {"blobs:sha", "manifests:new"}

    run(empty_database, tmp_path, scenario)


def test_a_push_that_comes_second_is_refused_and_refers_to_nothing_missing(
    empty_database, tmp_path
):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await prepare(factory, settings)
        refused = []

        async def deleting() -> None:
            async with factory() as db:
                await delete(await context_in(db, settings, repository), "old", OLD)
                await asyncio.sleep(0.3)  # stay open while the push arrives
                await db.commit()

        async def pushing() -> None:
            await asyncio.sleep(0.1)
            async with factory() as db:
                with pytest.raises(RegistryError) as error:
                    await push(await context_in(db, settings, repository), "new", NEW)
                refused.append(error.value.code)

        await asyncio.gather(deleting(), pushing())

        assert refused == ["MANIFEST_BLOB_UNKNOWN"]
        assert await state(factory, settings, repository) == set()

    run(empty_database, tmp_path, scenario)
```

In `backend/tests/test_route_guards.py`:

After

```python
    assert {"/api/v1/users/{user_id}", "/repository/{name}/{path:path}"} <= paths
```

add

```python
    assert {"/v2/", "/v2/token", "/v2/_catalog", "/v2/{name}/{path:path}"} <= paths
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/docker tests/test_route_guards.py -q`
Expected: collection error, `No module named 'megooarti.repositories.docker.format'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/docker/format.py`:

```python
"""The Docker format: a registry that Docker, Podman and containerd push to and pull from.

This is the only Docker module that touches the repository context. What a path means
and what a manifest refers to come from the pure functions beside it. Repositories of
this format are served by the registry API at `/v2/`, not under `/repository/`.

How an image is kept:

- A layer or an image configuration is a blob, stored once for the repository at
  `blobs/<digest>` and shared by every image in it.
- A manifest is stored at `manifests/<image>/<digest>`, with the blobs and manifests
  it refers to recorded beside it.
- A tag is a file at `tags/<image>/<tag>` that holds the manifest it names, so the
  stored file's own hash is the digest a client asks for, and the deployment policy
  applies to a tag as to any path.

Deleting a manifest removes what only it used. Pushing a manifest and deleting one take
the same lock, so a push never ends up referring to a blob a delete has just removed.
"""

from datetime import datetime, timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from megooarti.errors import ApiError
from megooarti.repositories import uploads
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.docker import manifests, names
from megooarti.repositories.docker.errors import RegistryError, unknown
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.storage.backends import StagedBlob

FORMAT = "docker"
_BLOB = "application/octet-stream"
# What serialises every change to which blobs a repository's manifests refer to.
_REFERENCES = "references"
# A blob no manifest refers to is removed once it has been here this long: a push that
# stopped half-way, or a layer of an image that never arrived.
UNUSED_BLOB_SECONDS = 86400
_SWEEP_AT_ONCE = 1000
_CATALOG_MOST = 10_000
_TAGS_DEFAULT = 1000


def _not_allowed(allowed: str) -> RegistryError:
    return RegistryError(
        405, "UNSUPPORTED", f"This address accepts {allowed}.", headers={"Allow": allowed}
    )


def _digest_invalid(message: str = "Only a lower-case SHA-256 digest is taken.") -> RegistryError:
    return RegistryError(400, "DIGEST_INVALID", message)


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


def _address(context: RepositoryContext, image: str, rest: str) -> str:
    """An address under the registry API. Relative: a registry is always at a host's root."""
    return f"/v2/{context.repository.name}/{image}/{rest}"


# --- Blobs ---------------------------------------------------------------------------


async def _blob(context: RepositoryContext, request: Request, parsed: names.DockerPath) -> Response:
    if not _is_read(request):
        # Layers go with the images that use them, not one by one.
        raise _not_allowed("GET, HEAD")
    try:
        response = await context.respond(names.blob_path(parsed.reference), request)
    except ApiError as error:
        if error.status_code != 404:
            raise
        raise unknown("BLOB_UNKNOWN", "No such blob.") from None
    response.headers["Docker-Content-Digest"] = parsed.reference
    return response


async def _keep(context: RepositoryContext, digest: str, staged: StagedBlob) -> None:
    """Store staged content as the blob it claims to be, unless it is here already.

    Raises DIGEST_INVALID, having discarded the content, if it is not that blob.
    """
    if staged.sha256 != names.hex_of(digest):
        await context.discard(staged)
        raise _digest_invalid("The content is not what the digest says.")
    # Two pushes of one layer may finish together. The second finds it stored.
    await context.lock(f"blob {digest}")
    if await context.stat(names.blob_path(digest)) is not None:
        await context.discard(staged)
        return
    await context.store(names.blob_path(digest), staged, content_type=_BLOB)


def _created(context: RepositoryContext, image: str, digest: str) -> Response:
    headers = {
        "Location": _address(context, image, f"blobs/{digest}"),
        "Docker-Content-Digest": digest,
    }
    return Response(status_code=201, headers=headers)


def _progress(
    context: RepositoryContext, image: str, upload: str, size: int, status: int
) -> Response:
    """What a client is told about an upload: where it is, and how much has arrived."""
    headers = {
        "Location": _address(context, image, f"blobs/uploads/{upload}"),
        "Range": f"0-{max(size - 1, 0)}",
        "Docker-Upload-UUID": upload,
    }
    return Response(status_code=status, headers=headers)


def _wanted_digest(request: Request) -> str | None:
    digest = request.query_params.get("digest")
    if digest is not None and not names.is_digest(digest):
        raise _digest_invalid()
    return digest


async def _start_upload(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    if request.method != "POST":
        raise _not_allowed("POST")
    context.require_write()
    mounted = request.query_params.get("mount")
    if mounted is not None and names.is_digest(mounted):
        # Every image of a repository shares its blobs, so one that is here is mounted.
        if await context.stat(names.blob_path(mounted)) is not None:
            return _created(context, parsed.image, mounted)
    digest = _wanted_digest(request)
    if digest is not None:
        # The whole blob in this one request.
        await context.release()  # the body needs no connection
        staged = await context.stage(request.stream())
        await _keep(context, digest, staged)
        return _created(context, parsed.image, digest)
    upload = await uploads.begin(context, parsed.image)
    return _progress(context, parsed.image, upload, 0, 202)


def _chunk_start(request: Request) -> int | None:
    """Where the client says its chunk starts, from `Content-Range: <start>-<end>`."""
    stated = request.headers.get("Content-Range")
    if stated is None:
        return None
    start = stated.removeprefix("bytes").strip().partition("-")[0]
    if not (start.isascii() and start.isdigit() and len(start) <= 18):
        raise RegistryError(400, "BLOB_UPLOAD_INVALID", "The Content-Range cannot be read.")
    return int(start)


async def _upload(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    image, upload = parsed.image, parsed.reference
    try:
        if request.method == "GET":
            found = await uploads.progress(context, upload, image)
            return _progress(context, image, upload, found.size, 204)
        if request.method == "DELETE":
            await uploads.abandon(context, upload, image)
            return Response(status_code=204)
        if request.method == "PATCH":
            size = await uploads.append(
                context, upload, image, request.stream(), at=_chunk_start(request)
            )
            return _progress(context, image, upload, size, 202)
        if request.method == "PUT":
            digest = _wanted_digest(request)
            if digest is None:
                raise _digest_invalid("Completing an upload needs the digest of its content.")
            await uploads.append(context, upload, image, request.stream())  # often empty
            staged = await uploads.complete(context, upload, image)
            await _keep(context, digest, staged)
            return _created(context, image, digest)
    except uploads.UnknownUpload:
        raise unknown("BLOB_UPLOAD_UNKNOWN", "No such upload in progress.") from None
    except uploads.OutOfOrder as error:
        raise RegistryError(
            416,
            "BLOB_UPLOAD_INVALID",
            "The chunk does not start where the upload ends.",
            headers={"Range": f"0-{max(error.size - 1, 0)}"},
        ) from None
    raise _not_allowed("GET, PATCH, PUT, DELETE")


# --- Manifests -----------------------------------------------------------------------


def _stored_path(image: str, reference: str) -> str:
    if names.is_digest(reference):
        return names.manifest_path(image, reference)
    return names.tag_path(image, reference)


async def _read_manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    path = _stored_path(parsed.image, parsed.reference)
    stored = await context.stat(path)
    if stored is None:
        raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
    response = await context.respond(path, request)
    response.headers["Docker-Content-Digest"] = f"sha256:{stored.sha256}"
    return response


async def _push_manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    image, reference = parsed.image, parsed.reference
    # Refused before the body is read; the facade checks each file again.
    context.require_write()
    raw = await context.receive(request.stream(), limit=manifests.MAX_BYTES)
    try:
        if raw is None:
            raise manifests.InvalidManifest("it is larger than 4 MiB")
        manifest = manifests.read(raw, request.headers.get("Content-Type"))
    except manifests.InvalidManifest as error:
        message = f"The manifest cannot be taken: {error}."
        raise RegistryError(400, "MANIFEST_INVALID", message) from None
    if names.is_digest(reference) and reference != manifest.digest:
        raise _digest_invalid("The manifest is not what the digest in its address says.")

    await context.lock(_REFERENCES)
    needed = [names.blob_path(digest) for digest in manifest.blobs]
    needed += [names.manifest_path(image, digest) for digest in manifest.manifests]
    missing = sorted(set(needed) - await context.present(needed))
    if missing:
        raise RegistryError(
            400,
            "MANIFEST_BLOB_UNKNOWN",
            "The manifest refers to something that has not been pushed.",
            detail=[path.rpartition("/")[2] for path in missing],
        )

    by_digest = names.manifest_path(image, manifest.digest)
    if await context.stat(by_digest) is None:
        staged = await context.stage_bytes(raw)
        await context.store(by_digest, staged, content_type=manifest.media_type, references=needed)
    if not names.is_digest(reference):
        tag = names.tag_path(image, reference)
        held = await context.stat(tag)
        # Pushing a tag again with what it already names changes nothing, whatever the
        # deployment policy and whatever the caller may do.
        if held is None or held.sha256 != names.hex_of(manifest.digest):
            staged = await context.stage_bytes(raw)
            try:
                await context.store(tag, staged, content_type=manifest.media_type)
            except ApiError as error:
                if error.code != "redeploy_disabled":
                    raise
                message = "The tag exists, and this repository does not let a tag be moved."
                raise RegistryError(409, "DENIED", message) from None
    headers = {
        "Location": _address(context, image, f"manifests/{manifest.digest}"),
        "Docker-Content-Digest": manifest.digest,
    }
    return Response(status_code=201, headers=headers)


async def _tags_naming(context: RepositoryContext, image: str, digest: str) -> list[str]:
    """The stored paths of the tags of an image that name a manifest."""
    wanted = names.hex_of(digest)
    held = await context.package_files("", image)
    return [file.path for file in held if file.sha256 == wanted]


async def _drop(context: RepositoryContext, image: str, digest: str) -> bool:
    """Remove a manifest, its tags, and what only it used. False if it was not there."""
    path = names.manifest_path(image, digest)
    referred = await context.references(path)
    if not await context.delete(path):  # the facade checks `delete`
        return False
    for tag in await _tags_naming(context, image, digest):
        await context.delete(tag)
    still_used = await context.referenced(referred)
    for target in referred:
        if target in still_used:
            continue
        if target.startswith("blobs/"):
            await context.delete(target)
            continue
        # A platform's manifest. It goes too, unless it has a tag of its own.
        platform = target.rpartition("/")[2]
        if not await _tags_naming(context, image, platform):
            await _drop(context, image, platform)
    return True


async def _delete_manifest(context: RepositoryContext, parsed: names.DockerPath) -> Response:
    image, reference = parsed.image, parsed.reference
    if names.is_digest(reference):
        await context.lock(_REFERENCES)
        removed = await _drop(context, image, reference)
    else:
        # A tag goes alone: what it named may be pinned by its digest.
        removed = await context.delete(names.tag_path(image, reference))
    if not removed:
        raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
    return Response(status_code=202)


async def _manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    if _is_read(request):
        return await _read_manifest(context, request, parsed)
    if request.method == "PUT":
        return await _push_manifest(context, request, parsed)
    if request.method == "DELETE":
        return await _delete_manifest(context, parsed)
    raise _not_allowed("GET, HEAD, PUT, DELETE")


# --- Tags and the catalog ------------------------------------------------------------


def _page(request: Request, default: int, most: int) -> tuple[int, str]:
    asked = request.query_params.get("n", "")
    plain = asked.isascii() and asked.isdigit() and len(asked) <= 6
    return (min(int(asked), most) if plain else default), request.query_params.get("last", "")


async def _tags(context: RepositoryContext, request: Request, parsed: names.DockerPath) -> Response:
    if not _is_read(request):
        raise _not_allowed("GET, HEAD")
    held = sorted(await context.versions("", parsed.image))
    if not held:
        raise unknown("NAME_UNKNOWN", "No such image.")
    count, last = _page(request, _TAGS_DEFAULT, _CATALOG_MOST)
    after = [tag for tag in held if tag > last]
    page = after[:count]
    headers = {}
    if count and len(after) > count:
        more = _address(context, parsed.image, f"tags/list?n={count}&last={page[-1]}")
        headers["Link"] = f'<{more}>; rel="next"'
    name = f"{context.repository.name}/{parsed.image}"
    return JSONResponse({"name": name, "tags": page}, headers=headers)


async def images(context: RepositoryContext) -> list[str]:
    """The images of a repository that have a tag, in order."""
    found, _ = await context.package_names("", limit=_CATALOG_MOST, offset=0)
    return [name for _, name in found]


class DockerFormat(Format):
    name = FORMAT
    served_at = "registry"
    # Proxy and group repositories need the registry's own handling.
    types = frozenset({"hosted"})

    def describe_component(self, path: str) -> ComponentKey | None:
        """A tag is a component: the image, and the tag as its version. Nothing else is."""
        named = names.tag_of(path)
        return None if named is None else ComponentKey("", *named)

    async def maintain(self, context: RepositoryContext, now: datetime) -> None:
        """Remove blobs that no manifest has referred to for a day."""
        await context.lock(_REFERENCES)
        before = now - timedelta(seconds=UNUSED_BLOB_SECONDS)
        for path in await context.unreferenced("blobs/", before=before, limit=_SWEEP_AT_ONCE):
            await context.sweep(path)

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = names.classify(path)
        if parsed.kind == "blob":
            return await _blob(context, request, parsed)
        if parsed.kind == "upload_start":
            return await _start_upload(context, request, parsed)
        if parsed.kind == "upload":
            return await _upload(context, request, parsed)
        if parsed.kind == "manifest":
            return await _manifest(context, request, parsed)
        if parsed.kind == "tags":
            return await _tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")


register(DockerFormat())
```

`backend/src/megooarti/repositories/docker/routes.py`:

```python
"""The container registry API, at `/v2/`.

Container clients only speak to `/v2/` at a host's root, so this is where Docker
repositories are served, all of them: the first part of an image's name is the
repository. Who is asking and whether they may read are decided here, before any
format code runs, as on the content route. What differs is the shape of an error and
the way a client is asked to sign in.
"""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.repositories import dispatch, remote, service
from megooarti.repositories.content import build_context
from megooarti.repositories.docker import errors, names
from megooarti.repositories.docker.errors import RegistryError
from megooarti.repositories.docker.format import FORMAT, images
from megooarti.security import registry_tokens
from megooarti.security.authentication import (
    Credentials,
    Principal,
    authorize,
    client_credentials,
    issue_registry_token,
)
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

router = APIRouter()

_METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]
_CATALOG_DEFAULT = 100
_CATALOG_MOST = 1000


def _unauthorized(message: str = "Authentication is required.") -> RegistryError:
    return RegistryError(401, "UNAUTHORIZED", message)


async def _challenge(request: Request, db: AsyncSession, scope: str | None) -> str:
    """How a client is told to sign in: where to fetch a registry token, and for what."""
    base = await get_setting(db, "base_url") or str(request.base_url)
    realm = f"{base.rstrip('/')}/v2/token"
    service_name = request.headers.get("Host", "registry")
    challenge = f'Bearer realm="{realm}",service="{service_name}"'
    return challenge if scope is None else f'{challenge},scope="{scope}"'


async def _answer(
    request: Request,
    db: AsyncSession,
    work: Callable[[], Awaitable[Response]],
    *,
    scope: str | None = None,
) -> Response:
    """Run a registry request, and put whatever goes wrong in the registry's shape."""
    try:
        response = await work()
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was kept; nobody is left to answer.
        log.info("upload_interrupted", path=request.url.path)
        return Response(status_code=400)
    except ApiError as error:
        await db.rollback()
        headers = {}
        if error.status_code == 401:
            headers["WWW-Authenticate"] = await _challenge(request, db, scope)
        return errors.response(error, headers)
    response.headers.update(errors.API_VERSION)
    return response


async def _caller(request: Request, credentials: Credentials) -> Principal:
    """Who is asking. A registry request always says so: there is no falling back.

    Without credentials the answer is the challenge, even while anonymous access is
    on: a client then fetches a registry token for the anonymous user, which is how
    it learns that it may.
    """
    if "Authorization" not in request.headers:
        raise _unauthorized()
    principal = await credentials.principal()
    if principal is None:
        raise _unauthorized()
    return principal


@router.get("/v2/", include_in_schema=False)
async def base(
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Is this a registry, and am I signed in?"""

    async def work() -> Response:
        await _caller(request, credentials)
        return JSONResponse({})

    return await _answer(request, db, work)


@router.get("/v2/token", include_in_schema=False)
async def token(
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Sign in: a user name and a password or API token in, a registry token out.

    Without credentials the token is the anonymous user's, if anonymous access is on.
    """
    try:
        signed_in = "Authorization" in request.headers
        principal = await credentials.principal() if signed_in else None
        value = await issue_registry_token(request, db, principal)
        await db.commit()
    except ApiError as error:
        await db.rollback()
        headers = (
            {"WWW-Authenticate": 'Basic realm="MegooArti"'} if error.status_code == 401 else {}
        )
        return errors.response(error, headers)
    now = utcnow()
    body = {
        "token": value,
        "access_token": value,
        "expires_in": registry_tokens.LIFETIME_SECONDS,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store", **errors.API_VERSION})


def _paging(request: Request) -> tuple[int, str]:
    asked = request.query_params.get("n", "")
    plain = asked.isascii() and asked.isdigit() and len(asked) <= 6
    count = min(int(asked), _CATALOG_MOST) if plain else _CATALOG_DEFAULT
    return count, request.query_params.get("last", "")


@router.get("/v2/_catalog", include_in_schema=False)
async def catalog(
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """The images the caller may read, in every Docker repository."""

    async def work() -> Response:
        principal = await _caller(request, credentials)
        count, last = _paging(request)
        found: list[str] = []
        for repository in await service.repositories_of(db, FORMAT):
            context = await build_context(db, request.app.state.settings, repository, principal)
            if not repository.online or not principal.allows(context.permission("read")):
                continue
            found.extend(f"{repository.name}/{image}" for image in await images(context))
        listed = sorted(name for name in found if name > last)
        page = listed[:count]
        headers = {}
        if count and len(listed) > count:
            headers["Link"] = f'</v2/_catalog?n={count}&last={page[-1]}>; rel="next"'
        await db.commit()
        return JSONResponse({"repositories": page}, headers=headers)

    return await _answer(request, db, work, scope="registry:catalog:*")


def _scope(name: str, path: str, method: str) -> str | None:
    """What a client should ask a token for, so that this request would be allowed."""
    image = names.classify(path).image
    if not image:
        return None
    actions = "pull" if method in ("GET", "HEAD") else "pull,push"
    return f"repository:{name}/{image}:{actions}"


@router.api_route("/v2/{name}/{path:path}", methods=_METHODS, include_in_schema=False)
async def repository_request(
    name: str,
    path: str,
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    async def work() -> Response:
        principal = await _caller(request, credentials)
        repository = await service.get_repository(db, name)
        if repository is None or repository.format != FORMAT:
            raise RegistryError(404, "NAME_UNKNOWN", "No such repository.")
        if len(name) + 1 + len(names.classify(path).image) > names.MAX_NAME_LENGTH:
            raise RegistryError(400, "NAME_INVALID", "The image's name is too long.")
        context = await build_context(
            db,
            request.app.state.settings,
            repository,
            principal,
            # Built on first use: most requests never reach a remote.
            outbound=lambda: remote.client_of(request.app),
        )
        if request.method in ("GET", "HEAD"):
            authorize(principal, context.permission("read"), scheme="Basic")
        if not repository.online:
            raise ApiError(503, "repository_offline", "This repository is offline.")
        response = await dispatch.serve(context, request, path)
        # Committing here, not in the format, means it cannot answer "stored" for a
        # change that was never committed.
        await db.commit()
        return response

    return await _answer(request, db, work, scope=_scope(name, path, request.method))
```

In `backend/src/megooarti/repositories/service.py`:

Before

```python
async def members(db: AsyncSession, group: Repository) -> list[Repository]:
```

add

```python
async def repositories_of(db: AsyncSession, format: str) -> list[Repository]:
    """Every repository of a format, in name order."""
    rows = await db.scalars(
        select(Repository).where(Repository.format == format).order_by(Repository.name_key)
    )
    return list(rows)
```

In `backend/src/megooarti/main.py`:

After

```python
from megooarti.repositories.api import router as repositories_router
```

add

```python
from megooarti.repositories.docker.routes import router as registry_router  # registers the format
```

After

```python
    app.include_router(content_router)  # /repository/..., outside the JSON API
```

add

```python
    app.include_router(registry_router)  # /v2/..., the container registry API
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/docker tests/test_route_guards.py -q`
Expected: 217 passed.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2153 passed, 1 skipped; no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/docker backend/tests/test_route_guards.py
git commit -m "feat(docker): the registry API and hosted repositories"
```

---

### Task 7: Real clients and documentation

**Files:**
- Create: `backend/tests/test_docker_client.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-11-docker-format-design.md`

**Interfaces:**
- Consumes: hosted Docker repositories and the registry API; `tests/containers.py` (`HTTP_PORT`, `PROJECT`, `call`); the `stack` and `administrator` fixtures.
- Produces: three Docker-marked tests in which the Docker client and daemon and skopeo use a hosted repository.

These tests run only with `pytest -m docker`. They drive the Docker client and daemon of the machine they run on. The first two need no internet access; the third pulls the skopeo image from quay.io. On a daemon that keeps its images in containerd, pushes and pulls go through containerd's registry client, so say in the final report which kind of daemon ran them.

- [ ] **Step 1: Write the real-client tests**

`backend/tests/test_docker_client.py`:

```python
"""Real container clients against the built image.

Run with `pytest -m docker`. This drives the Docker client and the daemon of the
machine it runs on, which is the one that also runs the stack: images are built from
nothing, pushed to MegooArti at 127.0.0.1, removed, and pulled back. A daemon that keeps
its images in containerd uses containerd's own registry client for that. The last
test uses skopeo, which is built on the image library Podman uses; its image is pulled
from quay.io, so that test needs internet access.

The Docker client is given a configuration directory of its own, so the user's sign-ins
and settings are neither read nor changed.
"""

import functools
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

REGISTRY = f"127.0.0.1:{HTTP_PORT}"
NETWORK = f"{PROJECT}_default"
SKOPEO = "quay.io/skopeo/stable:latest"
HOSTED = "docker-hosted"
RELEASES = "docker-releases"  # tags cannot be moved
USERNAME = "ci"
PASSWORD = "pushes-and-pulls-container-images"
READER = "reader"
IMAGE = f"{REGISTRY}/{HOSTED}/megooarti-test/hello"


@functools.cache
def daemon() -> str:
    """Where the Docker daemon in use listens. A configuration of our own does not say."""
    asked = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return asked.stdout.strip()


def configuration(directory: Path) -> Path:
    """A Docker client configuration of our own, so that the user's is left alone.

    It names a registry already, which makes the client keep what `docker login` learns
    in this directory and not in the credential store of the machine.
    """
    directory.mkdir()
    (directory / "config.json").write_text('{"auths": {"registry.invalid": {}}}', "utf-8")
    return directory


def docker(
    config: Path, *arguments: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the Docker client with a configuration of our own."""
    return subprocess.run(
        ["docker", "--config", str(config), "--host", daemon(), *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def registry(method: str, path: str, username: str = USERNAME, secret: str = PASSWORD):
    """A request to the registry API from outside: (status, headers, body)."""
    credentials = b64encode(f"{username}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"http://{REGISTRY}/v2/{path}",
        method=method,
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def build(config: Path, directory: Path, tag: str, text: str) -> None:
    """Build an image from nothing whose one file says `text`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "hello.txt").write_text(text, encoding="utf-8", newline="\n")
    (directory / "Dockerfile").write_text(
        "FROM scratch\nCOPY hello.txt /hello.txt\n", encoding="utf-8", newline="\n"
    )
    built = docker(config, "build", "--tag", tag, str(directory))
    assert built.returncode == 0, said(built)


def file_in(config: Path, image: str, directory: Path) -> str:
    """What `/hello.txt` says in an image the daemon holds."""
    made = docker(config, "create", image, "/nothing")
    assert made.returncode == 0, said(made)
    container = made.stdout.strip()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        copied = docker(config, "cp", f"{container}:/hello.txt", str(directory / "hello.txt"))
        assert copied.returncode == 0, said(copied)
        return (directory / "hello.txt").read_text(encoding="utf-8")
    finally:
        docker(config, "rm", container)


def sign_in(config: Path, username: str, password: str) -> subprocess.CompletedProcess[str]:
    return docker(
        config, "login", REGISTRY, "--username", username, "--password-stdin", stdin=password
    )


@pytest.fixture(scope="module")
def accounts(administrator) -> None:
    """Two Docker repositories, an account that may do everything in them, and a reader."""
    hosted = {"name": HOSTED, "format": "docker", "type": "hosted"}
    releases = {
        "name": RELEASES,
        "format": "docker",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    roles = [
        {"name": "docker-pushers", "permissions": ["repository:docker"]},
        {"name": "docker-readers", "permissions": [f"repository:docker:{HOSTED}:read"]},
    ]
    users = [
        {"username": USERNAME, "roles": ["docker-pushers"]},
        {"username": READER, "roles": ["docker-readers"]},
    ]
    for body in (hosted, releases):
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    for body in roles:
        status, _, answer = call("POST", "/roles", body, administrator)
        assert status == 201, answer
    for user in users:
        body = {**user, "display_name": "CI", "password": PASSWORD, "must_change_password": False}
        status, _, answer = call("POST", "/users", body, administrator)
        assert status == 201, answer


@pytest.fixture
def signed_in(accounts, tmp_path):
    """A Docker client configuration signed in as the pushing account."""
    config = configuration(tmp_path / "docker-config")
    login = sign_in(config, USERNAME, PASSWORD)
    assert login.returncode == 0, said(login)
    assert REGISTRY in json.loads((config / "config.json").read_text("utf-8"))["auths"]
    yield config
    held = docker(config, "image", "ls", "--quiet", "--filter", f"reference={REGISTRY}/*/*/*")
    for image in set(held.stdout.split()):
        docker(config, "rmi", "--force", image)


def test_docker_signs_in_pushes_and_pulls(signed_in, tmp_path):
    config = signed_in
    build(config, tmp_path / "v1", f"{IMAGE}:1.0", "hello from version one")

    # Push, forget the image, and pull it back.
    pushed = docker(config, "push", f"{IMAGE}:1.0")
    assert pushed.returncode == 0, said(pushed)
    assert docker(config, "rmi", f"{IMAGE}:1.0").returncode == 0
    pulled = docker(config, "pull", f"{IMAGE}:1.0")
    assert pulled.returncode == 0, said(pulled)
    assert file_in(config, f"{IMAGE}:1.0", tmp_path / "out1") == "hello from version one"

    # What the registry says of it is what the daemon was given.
    status, headers, _ = registry("HEAD", f"{HOSTED}/megooarti-test/hello/manifests/1.0")
    digest = headers["Docker-Content-Digest"]
    assert (status, digest in pushed.stdout, digest in pulled.stdout) == (200, True, True)
    status, _, tags = registry("GET", f"{HOSTED}/megooarti-test/hello/tags/list")
    assert (status, json.loads(tags)["tags"]) == (200, ["1.0"])
    status, _, catalog = registry("GET", "_catalog")
    assert f"{HOSTED}/megooarti-test/hello" in json.loads(catalog)["repositories"]

    # The same image under another tag, and by its digest.
    assert docker(config, "tag", f"{IMAGE}:1.0", f"{IMAGE}:latest").returncode == 0
    again = docker(config, "push", f"{IMAGE}:latest")
    assert again.returncode == 0, said(again)
    _, headers, _ = registry("HEAD", f"{HOSTED}/megooarti-test/hello/manifests/latest")
    assert headers["Docker-Content-Digest"] == digest
    by_digest = docker(config, "pull", f"{IMAGE}@{digest}")
    assert by_digest.returncode == 0, said(by_digest)

    # A tag moves, here. Where tags cannot be moved, the second push is refused.
    build(config, tmp_path / "v2", f"{IMAGE}:1.0", "hello from version two")
    moved = docker(config, "push", f"{IMAGE}:1.0")
    assert moved.returncode == 0, said(moved)
    release = f"{REGISTRY}/{RELEASES}/megooarti-test/hello:1.0"
    for text in ("the release", "not the release"):
        build(config, tmp_path / "release", release, text)
        kept = docker(config, "push", release)
        assert (kept.returncode == 0) == (text == "the release"), said(kept)

    # Without signing in there is nothing to pull, and a reader cannot push.
    nobody = configuration(tmp_path / "nobody")
    refused = docker(nobody, "pull", f"{IMAGE}:latest")
    assert refused.returncode != 0, "pulled without signing in"
    reader = configuration(tmp_path / "reader")
    login = sign_in(reader, READER, PASSWORD)
    assert login.returncode == 0, said(login)
    assert docker(reader, "pull", f"{IMAGE}:latest").returncode == 0
    # Docker does not send what a registry already has, so the reader pushes a new tag.
    assert docker(reader, "tag", f"{IMAGE}:latest", f"{IMAGE}:mine").returncode == 0
    denied = docker(reader, "push", f"{IMAGE}:mine")
    assert denied.returncode != 0, "pushed with the right to read only"
    assert "do not have permission" in denied.stderr, said(denied)  # our own words
    assert registry("HEAD", f"{HOSTED}/megooarti-test/hello/manifests/mine")[0] == 404
    wrong = sign_in(nobody, USERNAME, "not the password")
    assert wrong.returncode != 0, "signed in with a wrong password"

    # Deleting an image gives back the layers nothing else uses.
    status, headers, manifest = registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/latest")
    first = headers["Docker-Content-Digest"]
    listed = json.loads(manifest)
    children = [entry["digest"] for entry in listed.get("manifests", [])]
    layers = []
    for child in children or [first]:
        _, _, raw = registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/{child}")
        layers += [entry["digest"] for entry in json.loads(raw).get("layers", [])]
    assert layers, listed
    assert registry("DELETE", f"{HOSTED}/megooarti-test/hello/manifests/{first}")[0] == 202
    for gone in layers:
        assert registry("HEAD", f"{HOSTED}/megooarti-test/hello/blobs/{gone}")[0] == 404
    assert registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/latest")[0] == 404
    assert registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/1.0")[0] == 200  # version two


def test_anyone_pulls_what_the_anonymous_user_may_read(signed_in, administrator, tmp_path):
    public = f"{REGISTRY}/{HOSTED}/megooarti-test/public:1.0"
    build(signed_in, tmp_path / "public", public, "hello to everyone")
    pushed = docker(signed_in, "push", public)
    assert pushed.returncode == 0, said(pushed)
    assert docker(signed_in, "rmi", public).returncode == 0
    nobody = configuration(tmp_path / "nobody")
    assert docker(nobody, "pull", public).returncode != 0, "pulled before it was made public"

    status, _, users = call("GET", "/users", None, administrator)
    anonymous = next(user for user in users["items"] if user["username"] == "anonymous")
    path = f"/users/{anonymous['id']}"
    status, _, answer = call("PATCH", path, {"roles": ["docker-readers"]}, administrator)
    assert status == 200, answer
    status, _, answer = call("PUT", "/settings/anonymous-access", {"enabled": True}, administrator)
    assert status == 200, answer

    try:
        pulled = docker(nobody, "pull", public)
        assert pulled.returncode == 0, said(pulled)
        assert file_in(nobody, public, tmp_path / "out") == "hello to everyone"
        # Reading is all that was given, and only in that repository.
        assert docker(nobody, "tag", public, f"{public}-mine").returncode == 0
        assert docker(nobody, "push", f"{public}-mine").returncode != 0, "pushed without signing in"
        elsewhere = docker(nobody, "pull", f"{REGISTRY}/{RELEASES}/megooarti-test/hello:1.0")
        assert elsewhere.returncode != 0, "pulled from a repository that is not public"
    finally:
        call("PUT", "/settings/anonymous-access", {"enabled": False}, administrator)
    assert docker(nobody, "pull", public).returncode != 0, "pulled after it stopped being public"


def layer_holding(text: str) -> tuple[bytes, str]:
    """A layer with one file, as a compressed archive, and the digest of it uncompressed."""
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode="w") as archive:
        entry = tarfile.TarInfo("hello.txt")
        entry.size = len(text.encode())
        archive.addfile(entry, io.BytesIO(text.encode()))
    return gzip.compress(plain.getvalue(), mtime=0), _digest(plain.getvalue())


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_layout(directory: Path, name: str) -> tuple[bytes, set[str]]:
    """An OCI image layout holding one image for two platforms. Returns its index and blobs."""
    blobs: dict[str, bytes] = {}

    def keep(data: bytes) -> dict:
        blobs[_digest(data)] = data
        return {"digest": _digest(data), "size": len(data)}

    platforms = []
    for architecture in ("amd64", "arm64"):
        archive, diff_id = layer_holding(f"hello from {architecture}")
        config = json.dumps(
            {
                "architecture": architecture,
                "os": "linux",
                "rootfs": {"type": "layers", "diff_ids": [diff_id]},
            }
        ).encode()
        manifest = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {"mediaType": "application/vnd.oci.image.config.v1+json", **keep(config)},
                "layers": [
                    {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", **keep(archive)}
                ],
            }
        ).encode()
        platforms.append(
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                **keep(manifest),
                "platform": {"architecture": architecture, "os": "linux"},
            }
        )
    index = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": platforms,
        }
    ).encode()
    described = {"mediaType": "application/vnd.oci.image.index.v1+json", **keep(index)}
    described["annotations"] = {"org.opencontainers.image.ref.name": name}
    (directory / "blobs" / "sha256").mkdir(parents=True)
    for digest, data in blobs.items():
        (directory / "blobs" / "sha256" / digest.partition(":")[2]).write_bytes(data)
    (directory / "oci-layout").write_text('{"imageLayoutVersion": "1.0.0"}', encoding="utf-8")
    top = {"schemaVersion": 2, "manifests": [described]}
    (directory / "index.json").write_text(json.dumps(top), encoding="utf-8")
    return index, set(blobs)


def skopeo(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the skopeo image, in a copy of `directory`, beside the stack."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        "--entrypoint",
        "sh",
        SKOPEO,
        "-c",
        f"cp -r /src /work && cd /work && {script}",
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


def test_an_image_for_several_platforms_is_copied_in_and_out(accounts, tmp_path):
    work = tmp_path / "skopeo"
    work.mkdir()
    index, blobs = write_layout(work / "layout", "multi")
    there = f"docker://backend:8000/{HOSTED}/megooarti-test/multi:1.0"
    creds = f"{USERNAME}:{PASSWORD}"

    copied = skopeo(
        work,
        # What skopeo says as it works goes to the error stream: the output is ours.
        f"skopeo copy --all --dest-tls-verify=false --dest-creds {creds}"
        f" oci:layout:multi {there} >&2"
        f" && skopeo inspect --raw --tls-verify=false --creds {creds} {there} > /tmp/index.json"
        f" && skopeo copy --all --src-tls-verify=false --src-creds {creds}"
        f" {there} oci:back:multi >&2"
        " && cat /tmp/index.json && echo && ls back/blobs/sha256",
    )

    assert copied.returncode == 0, said(copied)
    served, _, listing = copied.stdout.partition("\n")
    assert served.encode() == index  # the manifest for both platforms, as it was pushed
    assert {f"sha256:{name}" for name in listing.split()} >= blobs  # and everything it needs
    status, headers, _ = registry("HEAD", f"{HOSTED}/megooarti-test/multi/manifests/1.0")
    assert (status, headers["Docker-Content-Digest"]) == (200, _digest(index))
    assert headers["Content-Type"] == "application/vnd.oci.image.index.v1+json"
```

- [ ] **Step 2: Run them**

Run: `uv run pytest -m docker tests/test_docker_client.py -q`
Expected: 3 passed. This builds the image from the working tree, so it is the first run of real clients against this plan's code. If a client fails, the assertion message carries the end of its output.

- [ ] **Step 3: Document Docker repositories**

In `README.md`:

Replace

```markdown
`raw` (arbitrary files by path), `maven`, `npm` and `pypi`.
```

with

```markdown
`raw` (arbitrary files by path), `maven`, `npm`, `pypi` and `docker`.
```

After

```markdown
Reading through a group needs `read` on the group only, for example
`repository:pypi:pypi-public:read`.
```

add

````markdown
### Docker repositories

MegooArti is a container registry for Docker, Podman and containerd. A Docker
repository is not used under `/repository/`: container clients speak to `/v2/` at the
root of a host, and the first part of an image's name says which repository it is in.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-hosted", "format": "docker", "type": "hosted"
}' http://localhost:8000/api/v1/repositories

docker login repo.example.com
docker tag my-app:1.0 repo.example.com/docker-hosted/team/my-app:1.0
docker push repo.example.com/docker-hosted/team/my-app:1.0
docker pull repo.example.com/docker-hosted/team/my-app:1.0
```

- **HTTPS.** Container clients refuse plain HTTP to every host but `localhost`, so
  put MegooArti behind HTTPS for clients on other machines. The registry has to be at
  the root of its host: a deployment under a path prefix cannot serve Docker. Behind a
  reverse proxy, set the base URL under `/api/v1/settings`: it is where clients are
  sent to sign in.
- **Signing in.** `docker login` takes a user name with a password or with an API
  token. The client is then given a registry token that lasts five minutes, and
  fetches a new one by itself. Disabling a user or revoking an API token takes effect
  at once; a changed password within five minutes. Tools that send HTTP Basic
  credentials or an API token with every request are accepted too.
- **Permissions.** Pulling needs `read`, pushing `add`, moving a tag `edit`, and
  deleting `delete`, for example `repository:docker:docker-hosted:read`.
- **Public images.** Turn on anonymous access and give the `anonymous` user a role
  with `read` on the repositories that are to be public. `docker pull` then works
  without `docker login`, for those repositories only.
- **Tags that cannot be moved.** With the deployment policy `disable_redeploy`, a tag
  that exists cannot be given to another image (`409`). Pushing the image it already
  names again changes nothing and is accepted.
- **Images for several platforms** are pushed and pulled as one. Docker's and the OCI's
  manifests and manifest lists are taken; the retired schema 1 is not.
- **A layer is stored once** in a repository, however many of its images use it, and
  is not uploaded again. Whoever may read a repository may fetch any layer in it by
  its digest.
- **Uploads are streamed to disk** in the chunks the client sends, whatever the size
  of the layer, and can be resumed. A layer must match its digest or it is not kept.
- **Deleting an image** is done by its digest, and removes the tags that name it and
  the layers nothing else in the repository uses. Deleting a tag removes the tag
  alone: the image can still be pulled by its digest. Docker has no command for
  either, so use the API:

  ```bash
  curl -u admin -I https://repo.example.com/v2/docker-hosted/team/my-app/manifests/1.0
  # Docker-Content-Digest: sha256:...
  curl -u admin -X DELETE https://repo.example.com/v2/docker-hosted/team/my-app/manifests/sha256:...
  ```

- **Cleaning up.** A layer that no image refers to, and an upload that was never
  finished, are removed after a day. A push that stops half-way leaves nothing behind
  for longer than that.
- **Listing.** `GET /v2/_catalog` lists the images you may read as
  `<repository>/<image>`, and `GET /v2/<repository>/<image>/tags/list` an image's tags.
- Errors under `/v2/` have the registry API's own shape, which container clients
  show: `{"errors": [{"code": "...", "message": "..."}]}`.
- Not available: the referrers API (clients fall back to tags), mounting a layer from
  another repository (it is uploaded instead), and deleting a single layer. Proxy and
  group Docker repositories are not available yet.
- **Clients.** Tested with the Docker client and daemon, whose pushes and pulls go
  through containerd's registry client, and with skopeo, which is built on the image
  library Podman uses.
````

- [ ] **Step 4: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-11-docker-format-design.md`:

After

```markdown
| `GET /v2/token` without credentials | A registry token for the anonymous user if anonymous access is on. Otherwise `401` |
```

add

```markdown
| `GET /v2/token` with a registry token | `401`. A registry token cannot be traded for another, so none outlives its five minutes |
```

Replace

```markdown
5. If the address names a tag, the tag is stored, or moved. The facade applies the deployment policy and the `add` and `edit` permissions to the tag's path.
```

with

```markdown
5. If the address names a tag, the tag is stored, or moved. The facade applies the deployment policy and the `add` and `edit` permissions to the tag's path. A tag that already names this manifest is left as it is: clients push an image again as a matter of course, and that must not fail where tags cannot be moved.
```

Replace

```markdown
| `security/registry_tokens.py` | Seal and read a registry token; grant one for a request's credentials |
```

with

```markdown
| `security/registry_tokens.py` | Seal and read a registry token |
| `security/authentication.py` | Grant a registry token for a request's credentials; accept one as a `Bearer` credential |
```

Replace

```markdown
| `repositories/uploads.py`, `content.py`, `models.py`, `formats.py`, `routes.py`, `storage/backends.py`, `maintenance.py`, `main.py` | The core changes of section 4 |
```

with

```markdown
| `repositories/uploads.py`, `upkeep.py`, `content.py`, `models.py`, `formats.py`, `routes.py`, `storage/backends.py`, `secrets_box.py`, `main.py` | The core changes of section 4 |
```

Replace

```markdown
  - *Plan 7a:* the Docker client and daemon sign in, build a small image from nothing, push it, remove it locally, pull it and run it; push it again under another tag; and are refused when they should be. A second client that uses Podman's image library copies an image with several platforms to the repository and back, and compares it. A deleted image's layers are gone from the blob store.
```

with

```markdown
  - *Plan 7a:* the Docker client and daemon sign in, build a small image from nothing, push it, remove it locally, pull it and read its file back out of it; push it again under another tag; pull without signing in what the anonymous user may read; and are refused when they should be. A second client that uses Podman's image library copies an image with several platforms to the repository and back, and compares it. A deleted image's layers are gone from the repository.
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2153 passed, 1 skipped; no findings.

Run: `uv run pytest -m docker -q`
Expected: 19 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_docker_client.py README.md docs/superpowers/specs/2026-10-11-docker-format-design.md
git commit -m "test(docker): push and pull with Docker and skopeo; document Docker repositories"
```
