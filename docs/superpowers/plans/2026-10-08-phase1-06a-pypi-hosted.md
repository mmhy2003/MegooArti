# Hosted PyPI Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `twine upload` and `uv publish` publish to a hosted PyPI repository, `pip` and `uv` install from it, and an API token works the way Python tools send it: as the password of the user `__token__`.

**Architecture:** A `pypi` format package classifies each request path with pure functions and answers through the storage facade. An upload form is read as it streams: the file goes straight to the blob store's staging area and only the few fields that are used are kept. A project's index page is generated on every request from the files stored, with relative links, at one address that other spellings redirect to. The security package learns one thing: the name `__token__` stands for whoever owns the token sent with it.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, `python-multipart` (its push parser), pytest + pytest-asyncio, Docker (the `python:3.13-slim` image, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-08-pypi-format-design.md](../specs/2026-10-08-pypi-format-design.md), sections 4.1, 5, 6, 7, 10, 11 and the plan 6a part of 12. Business requirements: [docs/BRD.md](../../BRD.md) FMT-3 (hosted), SEC-9, NFR-1.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `authenticate_secret` treats the name `__token__` as nobody's: with an API token it looks the user up by the token alone, and with anything else it is a failed attempt counted against the address. `create_user` refuses the name. | One function already checks every name and secret, so every format and the REST API get this at once, with the same limits. |
| P2 | What a file requires (`requires_python`) is recorded on the file; the name as written, the version and the summary are recorded on its component. `store` gains `attributes` for the file itself. | A page says what each file requires. Kept on the component, an upload of a second file of the same version replaced it for the first. Found while the plan's code was being tried. |
| P3 | The form is read with `python-multipart`'s push parser. The `content` part is handed on piece by piece; seven fields are kept, each up to 4 KiB; every other field is read past without being kept. | The file can be gigabytes and a description megabytes. Neither may be held in memory. |
| P4 | The form's file pieces come out of an async generator that reads the request, and that generator is what `context.stage` consumes. | The file is written once, to the place it will stay, with no second temporary copy. |
| P5 | A file is stored at `packages/<project>/<version>/<file name>`, with the version the form declares. The file's name must fit the project; the version in the name is not compared with the declared one. | Tools write the same version in different spellings in a file name. The project check is the one installers apply. |
| P6 | Index pages use relative links and are served at one address. `simple`, a project page without its slash, and a name that is not in its normal form answer `301` with a relative `Location`. | A page is then the same for every client, whatever host or proxy prefix it used. |
| P7 | A page's `ETag` is the SHA-256 of its bytes, and its `Last-Modified` is the time of the request. | A generated page has no time of its own; clients revalidate with `ETag`. |
| P8 | Wheels (`.whl`) and source distributions (`.tar.gz`, `.zip`) are taken. A `blake2_256_digest` is not checked. | They are what current tools upload. The blob store does not compute BLAKE2. |
| P9 | The root index lists at most 100,000 projects. | Installers never ask for it; it must not be unbounded. |
| P10 | In this plan the format offers only `hosted`. Plan 6b adds `proxy` and `group`. | A proxy on the generic engine would serve the remote's page, whose links bypass MegooArti. |
| P11 | The real-client test builds its two distributions with the standard library, and installs twine and uv from pypi.org. It uses `uv publish --check-url` for files that are already there, not `twine upload --skip-existing`. | No build backend is needed in the container. twine itself refuses `--skip-existing` for any index but pypi.org; uv does not send the token to the check address, so the address carries it. Found by running the clients. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; settings prefixed `MEGOOARTI_` and listed in `README.md`; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; only the security package reads `Principal.patterns`; content responses always carry `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; formats do not commit, the route does; a token or password is never logged; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds one dependency, `python-multipart`, and no migration and no setting.**
- **The format's name is `pypi`.** Permissions are `repository:pypi:<name>:<action>`.
- **Only `pypi/format.py` touches the repository context.** `pypi/names.py`, `pypi/pages.py` and `pypi/upload.py` are pure: no database, no files, no clock.
- **An upload is never held in memory**, and the connection is given back before its body is read.
- **Everything a client declared that reaches a page is HTML-escaped.**
- **A project is always stored and listed under its normal form** (PEP 503).
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **An upload that is not what it says:** a file that does not match its digests; a name the file does not fit; path characters in a version or a file name; no file, or two; a form cut short, or not a form; too many parts; a field megabytes long. Each is refused, and nothing is left in the database or in the staging area (Tasks 5, 6).
2. **`__token__`.** It takes a token and nothing else; a token whose owner is disabled is refused; guesses under the name are limited like any others, and a valid token still works from a blocked address; nobody can be given the name (Task 1).
3. **An account with exactly one permission.** `add` uploads a new file and cannot replace one; `edit` replaces and cannot add; `delete` removes; `read` reads. None does another's job (Task 6).
4. **What a client declares, shown on a page.** A `requires_python` written to break out of its attribute is escaped (Tasks 4, 6).
5. **The same thing asked for in another spelling:** a project by any of its names, a page without its slash, a file path with a name that is not in its normal form, addresses that mean nothing (Tasks 3, 6).

---

### Task 1: Security: an API token under the name `__token__`

**Files:**
- Modify: `backend/src/megooarti/security/users.py`
- Modify: `backend/src/megooarti/security/authentication.py`
- Test: `backend/tests/security/test_authentication.py`
- Test: `backend/tests/security/test_users.py`

**Interfaces:**
- Consumes: `authenticate_secret`, `_authenticate_token`, `_checked`, `_no_match`, `users.normalise_username`, `users.create_user`.
- Produces:
  - `users.TOKEN_USERNAME = "__token__"`.
  - `authenticate_secret(db, request, "__token__", <token>)` returns the token's owner and the token. With any other secret it raises `401`, or `429` once the address is blocked.
  - `users.create_user(..., username="__token__")` raises `422 validation_error` with the field `username`.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/tests/security/test_authentication.py`:

```python
async def test_basic_with_the_token_user_name_is_the_tokens_owner(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    await make_user("dana", roles=["admin"])
    token = await make_token(root)

    for name in ("__token__", "__TOKEN__", " __token__ "):
        response = await client.get(READ, headers=basic(name, token))
        assert response.json() == {"user": "root", "method": "token"}


async def test_the_token_user_name_takes_nothing_but_a_token(client, make_user, make_token, db):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    with_password = await client.get(READ, headers=basic("__token__", PASSWORD))
    with_unknown = await client.get(READ, headers=basic("__token__", "mga_" + "x" * 43))
    await disable_user(db, "root")
    with_a_disabled_owner = await client.get(READ, headers=basic("__token__", token))

    for response in (with_password, with_unknown, with_a_disabled_owner):
        assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_guesses_under_the_token_user_name_are_limited_by_address(
    client, make_user, make_token
):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    for number in range(5):
        await client.get(READ, headers=basic("__token__", f"guess number {number}"))

    blocked = await client.get(READ, headers=basic("__token__", "one more guess"))
    by_token = await client.get(READ, headers=basic("__token__", token))

    assert blocked.status_code == 429
    assert by_token.status_code == 200  # a valid token is accepted even from a blocked address
```

Add to the end of `backend/tests/security/test_users.py`:

```python
@pytest.mark.parametrize("username", ["__token__", " __TOKEN__ "])
async def test_the_name_that_stands_for_a_token_cannot_be_a_users(db, username):
    error = await error_of(create(db, username))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == "username"
    assert await users.get_user_by_username(db, "__token__") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/security/test_authentication.py tests/security/test_users.py -q`
Expected: 4 failures. A token under `__token__` is `401`, because the name is compared with the owner's; a user named `__token__` is created. `test_the_token_user_name_takes_nothing_but_a_token` passes already: it states what must stay true.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/security/users.py`:

Replace

```python
from megooarti.security.sessions import delete_user_sessions


@dataclass(frozen=True)
```

with

```python
from megooarti.security.sessions import delete_user_sessions

# The name Python's packaging tools send with an API token (`__token__` and the token
# as HTTP Basic credentials). It stands for whoever owns the token, so nobody has it.
TOKEN_USERNAME = "__token__"


@dataclass(frozen=True)
```

Replace

```python
    username = normalise_username(username)
    if await get_user_by_username(db, username) is not None:
        raise ApiError(409, "conflict", f"A user named {username} already exists.")
```

with

```python
    username = normalise_username(username)
    if username == TOKEN_USERNAME:
        details = [
            {"field": "username", "message": "This name is reserved for signing in with a token."}
        ]
        raise ApiError(422, "validation_error", "The request is not valid.", details)
    if await get_user_by_username(db, username) is not None:
        raise ApiError(409, "conflict", f"A user named {username} already exists.")
```

In `backend/src/megooarti/security/authentication.py`:

Replace

```python
    Returns the token too when the secret was one. Raises 401 or 429. HTTP Basic
    credentials are checked here, and so is anything else that takes a name and a
    secret, so that the limits on failed attempts are the same everywhere.
    """
    if secret.startswith(TOKEN_PREFIX):
```

with

```python
    Returns the token too when the secret was one. Raises 401 or 429. HTTP Basic
    credentials are checked here, and so is anything else that takes a name and a
    secret, so that the limits on failed attempts are the same everywhere.

    The name `__token__` is nobody's: with it, the token alone says who is asking.
    """
    if users.normalise_username(username) == users.TOKEN_USERNAME:
        if secret.startswith(TOKEN_PREFIX):
            return await _authenticate_token(db, request, secret)
        # Not a token at all. A failed attempt, counted against the address.
        return await _checked(db, request, None, _no_match)
    if secret.startswith(TOKEN_PREFIX):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/security -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/security backend/tests/security
git commit -m "feat(security): accept an API token under the user name __token__"
```

---

### Task 2: Core: the files of a package, and what is recorded about a file

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py`
- Test: `backend/tests/repositories/test_content_components.py`

**Interfaces:**
- Consumes: `context.store`, `context._record` (which already takes `attributes`, for a proxy's cached files).
- Produces:
  - `content.PackageFile(path: str, version: str, size: int, sha256: str, modified: datetime, attributes: dict, component_attributes: dict)`.
  - `await context.package_files(namespace: str, name: str) -> list[PackageFile]`, ordered by path.
  - `await context.store(path, staged, *, content_type=None, kind="asset", attributes=None, component_attributes=None)`: `attributes`, when given, become what is recorded about the file itself. Left out, what was recorded stays.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/test_content_components.py`:

Before

```python
import pytest
from sqlalchemy import select
```

add

```python
import hashlib
```

Replace

```python
from megooarti.repositories.content import ComponentInfo
```

with

```python
from megooarti.repositories.content import ComponentInfo, PackageFile
```

Add to the end of `backend/tests/repositories/test_content_components.py`:

```python
async def test_package_files_lists_every_file_of_every_version(context):
    first, _ = await store(
        context,
        "acme/app/1.0/app.tgz",
        b"one",
        attributes={"kind": "source"},
        component_attributes={"n": 1},
    )
    second, _ = await store(context, "acme/app/1.0/app.whl", b"three")
    third, _ = await store(
        context, "acme/app/2.0/app.tgz", b"second", component_attributes={"n": 2}
    )
    await store(context, "acme/other/1.0/other.tgz")
    await store(context, "other/app/1.0/app.tgz")
    await store(context, "loose.txt")

    files = await context.package_files("acme", "app")

    assert files == [
        PackageFile(
            path="acme/app/1.0/app.tgz",
            version="1.0",
            size=3,
            sha256=hashlib.sha256(b"one").hexdigest(),
            modified=first.updated_at,
            attributes={"kind": "source"},
            component_attributes={"n": 1},
        ),
        PackageFile(
            path="acme/app/1.0/app.whl",
            version="1.0",
            size=5,
            sha256=hashlib.sha256(b"three").hexdigest(),
            modified=second.updated_at,
            attributes={},
            component_attributes={"n": 1},
        ),
        PackageFile(
            path="acme/app/2.0/app.tgz",
            version="2.0",
            size=6,
            sha256=hashlib.sha256(b"second").hexdigest(),
            modified=third.updated_at,
            attributes={},
            component_attributes={"n": 2},
        ),
    ]
    assert await context.package_files("acme", "nothing") == []


async def test_what_is_recorded_about_a_file_stays_until_it_is_given_again(context):
    await store(context, "acme/app/1.0/app.tgz", b"one", attributes={"kind": "source"})

    await store(context, "acme/app/1.0/app.tgz", b"two")
    kept = (await context.package_files("acme", "app"))[0].attributes
    await store(context, "acme/app/1.0/app.tgz", b"three", attributes={"kind": "rebuilt"})
    replaced = (await context.package_files("acme", "app"))[0].attributes

    assert (kept, replaced) == ({"kind": "source"}, {"kind": "rebuilt"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_components.py -q`
Expected: collection error, `cannot import name 'PackageFile' from 'megooarti.repositories.content'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/content.py`:

Before

```python
class TooLarge(Exception):
    """A file that was to be read into memory is larger than the caller allows."""
```

add

```python
@dataclass(frozen=True)
class PackageFile:
    """One file of a package, with what its version's component says."""

    path: str
    version: str
    size: int
    sha256: str
    modified: datetime
    attributes: dict[str, Any]  # the file's own
    component_attributes: dict[str, Any]
```

Before

```python
    async def component(self, namespace: str, name: str, version: str) -> ComponentInfo | None:
```

add

```python
    async def package_files(self, namespace: str, name: str) -> list[PackageFile]:
        """Every file of every version of a package, ordered by path."""
        rows = await self.db.execute(
            select(
                Asset.path,
                Component.version,
                Blob.size,
                Blob.sha256,
                Asset.updated_at,
                Asset.attributes,
                Component.attributes,
            )
            .join(Component, Component.id == Asset.component_id)
            .join(Blob, Blob.id == Asset.blob_id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
            )
            .order_by(Asset.path)
        )
        return [PackageFile(*row) for row in rows]
```

In `backend/src/megooarti/repositories/content.py`:

Replace

```python
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

with

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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/content.py backend/tests/repositories/test_content_components.py
git commit -m "feat(repositories): list the files of a package, and record attributes of a file"
```

---

### Task 3: PyPI names, paths and file names

**Files:**
- Create: `backend/src/megooarti/repositories/pypi/__init__.py` (empty)
- Create: `backend/src/megooarti/repositories/pypi/names.py`
- Create: `backend/tests/repositories/pypi/__init__.py` (empty)
- Test: `backend/tests/repositories/pypi/test_names.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `names.normalise(name: str) -> str`, `names.is_valid_name(name: str) -> bool`, `names.is_valid_segment(text: str) -> bool`, `names.MAX_NAME_LENGTH`.
  - `names.PypiPath(kind, project="", version="", filename="", slash=False)`; `kind` is `repository`, `index`, `page`, `file`, `metadata` or `other`.
  - `names.classify(path: str) -> PypiPath`. For a page, `project` is as it was written; for a file it is always the normal form.
  - `names.version_of(project: str, filename: str) -> str | None`: `project` in its normal form; `None` if the file does not fit it.
  - `names.file_path(project, version, filename) -> str`, and `names.UPLOADABLE`.

- [ ] **Step 1: Write the failing tests**

Create the two empty `__init__.py` files, then:

`backend/tests/repositories/pypi/test_names.py`:

```python
import pytest

from megooarti.repositories.pypi import names
from megooarti.repositories.pypi.names import PypiPath, classify, version_of


@pytest.mark.parametrize(
    ("written", "normal"),
    [
        ("requests", "requests"),
        ("Django", "django"),
        ("zope.interface", "zope-interface"),
        ("typing_extensions", "typing-extensions"),
        ("A__weird.-_Name", "a-weird-name"),
    ],
)
def test_a_name_has_one_normal_form(written, normal):
    assert names.normalise(written) == normal
    assert names.normalise(normal) == normal


@pytest.mark.parametrize("name", ["requests", "Django", "zope.interface", "a", "A1", "x-y_z.0"])
def test_valid_names(name):
    assert names.is_valid_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-leading",
        "trailing-",
        ".hidden",
        "has space",
        "sl/ash",
        "ünïcode",
        "a" * 129,
        "..",
        "a@b",
    ],
)
def test_invalid_names(name):
    assert not names.is_valid_name(name)


@pytest.mark.parametrize(
    "segment", ["1.0", "1!2.0", "1.0+local.1", "pkg-1.0-py3-none-any.whl", "2.0.0a1", "a_b"]
)
def test_valid_versions_and_file_names(segment):
    assert names.is_valid_segment(segment)


@pytest.mark.parametrize("segment", ["", ".", "..", "a/b", "a b", "a%2fb", "a\\b", "x" * 256, "é"])
def test_invalid_versions_and_file_names(segment):
    assert not names.is_valid_segment(segment)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", PypiPath("repository")),
        ("simple", PypiPath("index")),
        ("simple/", PypiPath("index", slash=True)),
        ("simple/requests/", PypiPath("page", project="requests", slash=True)),
        ("simple/Zope.Interface", PypiPath("page", project="Zope.Interface")),
        (
            "packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl",
            PypiPath(
                "file",
                project="requests",
                version="2.31.0",
                filename="requests-2.31.0-py3-none-any.whl",
            ),
        ),
        (
            "packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl.metadata",
            PypiPath(
                "metadata",
                project="requests",
                version="2.31.0",
                filename="requests-2.31.0-py3-none-any.whl",
            ),
        ),
        (
            "packages/zope-interface/1!6.0+local/zope.interface-6.0.tar.gz",
            PypiPath(
                "file",
                project="zope-interface",
                version="1!6.0+local",
                filename="zope.interface-6.0.tar.gz",
            ),
        ),
    ],
)
def test_paths_are_classified(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "simple/-bad-",
        "simple/requests/extra",
        "simple//",
        "packages",
        "packages/requests",
        "packages/requests/2.31.0",
        "packages/Requests/2.31.0/requests-2.31.0.tar.gz",  # not the normal form
        "packages/zope.interface/6.0/zope.interface-6.0.tar.gz",
        "packages/requests/../requests-2.31.0.tar.gz",
        "packages/requests/2.31.0/requests-2.31.0.tar.gz/",
        "packages/requests/2.31.0/requests-2.31.0.tar.gz/more",
        "packages/requests/2.31.0/.metadata",
        "pypi/requests/json",
        "simple/requests/index.html",
    ],
)
def test_everything_else_is_other(path):
    assert classify(path).kind == "other"


@pytest.mark.parametrize(
    ("project", "filename", "version"),
    [
        ("requests", "requests-2.31.0-py3-none-any.whl", "2.31.0"),
        ("requests", "requests-2.31.0.tar.gz", "2.31.0"),
        ("zope-interface", "zope.interface-6.0-cp312-cp312-manylinux_2_17_x86_64.whl", "6.0"),
        ("zope-interface", "zope_interface-6.0.tar.gz", "6.0"),
        ("typing-extensions", "typing_extensions-4.9.0-py3-none-any.whl", "4.9.0"),
        ("some-pkg", "some_pkg-1.0-1-py3-none-any.whl", "1.0"),  # with a build number
        ("my-package", "my-package-1.0.tar.gz", "1.0"),  # an old name with a hyphen
        ("my-package", "My.Package-1.0.zip", "1.0"),
        ("pyyaml", "PyYAML-3.10.tar.bz2", "3.10"),
        ("pkg", "pkg-1.0+local.tgz", "1.0+local"),
        ("pkg", "pkg-1.0.tar.xz", "1.0"),
        ("pkg", "pkg-1.0-py2.7.egg", "1.0"),
        ("pkg", "pkg-1.0.win32-py2.7.exe", "1.0.win32"),
        ("a-b", "a-b-c-1.0.tar.gz", "c-1.0"),  # the name is the project's, the rest is not ours
    ],
)
def test_the_version_is_read_from_the_file_name(project, filename, version):
    assert version_of(project, filename) == version


@pytest.mark.parametrize(
    ("project", "filename"),
    [
        ("requests", "urllib3-2.0.0-py3-none-any.whl"),
        ("requests", "urllib3-2.0.0.tar.gz"),
        ("requests", "requests-2.31.0-py3-none.whl"),  # too few parts for a wheel
        ("requests", "requests-2.31.0-1-py3-none-any-extra.whl"),
        ("requests", "requests--py3-none-any.whl"),
        ("requests", "requests.tar.gz"),
        ("requests", "requests-.tar.gz"),
        ("requests", "requests-2.31.0.txt"),
        ("requests", "requests-2.31.0"),
        ("requests", "-2.31.0.tar.gz"),
        ("requests", ""),
    ],
)
def test_a_file_that_does_not_fit_its_project_has_no_version(project, filename):
    assert version_of(project, filename) is None


def test_stored_paths():
    assert names.file_path("requests", "2.31.0", "requests-2.31.0.tar.gz") == (
        "packages/requests/2.31.0/requests-2.31.0.tar.gz"
    )
    assert classify(names.file_path("requests", "2.31.0", "requests-2.31.0.tar.gz")).kind == "file"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi/test_names.py -q`
Expected: collection error, `No module named 'megooarti.repositories.pypi'` (the source package's `__init__.py` is part of Step 3).

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/pypi/names.py`:

```python
"""PyPI project names, request paths and file names.

Pure functions. A project has many spellings and one normal form (PEP 503); everything
stored is keyed by the normal form.
"""

import re
from dataclasses import dataclass

MAX_NAME_LENGTH = 128
_MAX_SEGMENT_LENGTH = 255
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_RUN = re.compile(r"[-_.]+")
# A version or a file name, as one segment of a path.
_SEGMENT = re.compile(r"[A-Za-z0-9._+!-]+")

# What a hosted repository takes: wheels and source distributions.
UPLOADABLE = (".whl", ".tar.gz", ".zip")
_SOURCE = (".tar.gz", ".zip", ".tar.bz2", ".tar.xz", ".tgz")
# Old binary kinds a proxy still meets. Their names carry more than a version.
_LEGACY = (".egg", ".exe", ".msi")
_METADATA = ".metadata"


@dataclass(frozen=True)
class PypiPath:
    """A path, classified. Fields that do not apply to its kind are left empty."""

    kind: str  # repository, index, page, file, metadata or other
    project: str = ""  # page: as it was written; file and metadata: the normal form
    version: str = ""
    filename: str = ""  # metadata: the name of the file it describes
    slash: bool = False  # whether the path ended in a slash


_OTHER = PypiPath("other")


def normalise(name: str) -> str:
    """A project name in its normal form: lower case, runs of `-_.` as one hyphen."""
    return _RUN.sub("-", name).lower()


def is_valid_name(name: str) -> bool:
    return len(name) <= MAX_NAME_LENGTH and _NAME.fullmatch(name) is not None


def is_valid_segment(text: str) -> bool:
    """Whether this can be a version or a file name in a path."""
    if text in (".", "..") or len(text) > _MAX_SEGMENT_LENGTH:
        return False
    return _SEGMENT.fullmatch(text) is not None


def file_path(project: str, version: str, filename: str) -> str:
    """Where a file is stored, and requested. `project` is in its normal form."""
    return f"packages/{project}/{version}/{filename}"


def version_of(project: str, filename: str) -> str | None:
    """The version a file belongs to, read from its name.

    `project` is in its normal form. None if the name is not that of a file of the
    project: installers ignore such files too.
    """
    if filename.endswith(".whl"):
        parts = filename[: -len(".whl")].split("-")
        if len(parts) not in (5, 6) or normalise(parts[0]) != project:
            return None
        return parts[1] or None
    extension = next((known for known in _SOURCE + _LEGACY if filename.endswith(known)), None)
    if extension is None:
        return None
    stem = filename[: -len(extension)]
    # The longest prefix that is the project's name: names may contain hyphens.
    for position in range(len(stem) - 1, 0, -1):
        if stem[position] == "-" and normalise(stem[:position]) == project:
            rest = stem[position + 1 :]
            return (rest.partition("-")[0] if extension in _LEGACY else rest) or None
    return None


def classify(path: str) -> PypiPath:
    """What a request path is. One trailing slash is ignored, and remembered."""
    if path == "":
        return PypiPath("repository")
    slash = path.endswith("/")
    segments = (path[:-1] if slash else path).split("/")
    if segments == ["simple"]:
        return PypiPath("index", slash=slash)
    if len(segments) == 2 and segments[0] == "simple" and is_valid_name(segments[1]):
        return PypiPath("page", project=segments[1], slash=slash)
    if len(segments) == 4 and segments[0] == "packages" and not slash:
        _, project, version, filename = segments
        kind = "file"
        if filename.endswith(_METADATA):
            kind, filename = "metadata", filename[: -len(_METADATA)]
        valid = (
            is_valid_name(project)
            and project == normalise(project)
            and is_valid_segment(version)
            and is_valid_segment(filename)
        )
        if valid:
            return PypiPath(kind, project=project, version=version, filename=filename)
    return _OTHER
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/pypi/test_names.py -q`
Expected: 85 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/pypi backend/tests/repositories/pypi
git commit -m "feat(pypi): project names, request paths and the version in a file name"
```

---

### Task 4: Index pages

**Files:**
- Create: `backend/src/megooarti/repositories/pypi/pages.py`
- Test: `backend/tests/repositories/pypi/test_pages.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pages.Link(filename: str, version: str, digest: str = "", requires_python: str | None = None)`; `digest` is `sha256=<hex>`.
  - `pages.project_page(project: str, links: Iterable[Link]) -> bytes`; `project` in its normal form.
  - `pages.root_page(projects: Iterable[str]) -> bytes`.
  - `pages.head(title) -> bytes`, `pages.foot() -> bytes`, `pages.link_line(project, link) -> bytes`, for a page written piece by piece (plan 6b).
  - `pages.CONTENT_TYPE = "text/html; charset=utf-8"`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/pypi/test_pages.py`:

```python
from html.parser import HTMLParser

from megooarti.repositories.pypi import pages
from megooarti.repositories.pypi.pages import Link

SHA = "a" * 64


class Anchors(HTMLParser):
    """The links of a page, as a browser or pip would read them."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[dict[str, str | None], str]] = []
        self.metas: dict[str, str | None] = {}
        self._open: dict[str, str | None] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open = dict(attrs)
        if tag == "meta":
            self.metas[dict(attrs).get("name")] = dict(attrs).get("content")

    def handle_data(self, data):
        if self._open is not None:
            self.found.append((self._open, data))
            self._open = None


def read(page: bytes) -> Anchors:
    parser = Anchors()
    parser.feed(page.decode())
    return parser


def test_a_project_page_lists_each_file_with_its_hash():
    page = pages.project_page(
        "requests",
        [
            Link("requests-2.31.0.tar.gz", "2.31.0", f"sha256={SHA}"),
            Link("requests-2.31.0-py3-none-any.whl", "2.31.0", f"sha256={SHA}", ">=3.7"),
        ],
    )

    anchors = read(page)
    assert page.startswith(b"<!DOCTYPE html>")
    assert anchors.metas == {"pypi:repository-version": "1.0"}
    assert anchors.found == [
        (
            {"href": f"../../packages/requests/2.31.0/requests-2.31.0.tar.gz#sha256={SHA}"},
            "requests-2.31.0.tar.gz",
        ),
        (
            {
                "href": "../../packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl"
                f"#sha256={SHA}",
                "data-requires-python": ">=3.7",
            },
            "requests-2.31.0-py3-none-any.whl",
        ),
    ]


def test_what_a_file_declares_is_escaped_in_the_page():
    hostile = '">3.8"><script>alert(1)</script>'
    page = pages.project_page("pkg", [Link("pkg-1.0.tar.gz", "1.0", "", hostile)])

    assert b"<script>" not in page
    assert b"&gt;3.8" in page
    assert read(page).found == [
        (
            {"href": "../../packages/pkg/1.0/pkg-1.0.tar.gz", "data-requires-python": hostile},
            "pkg-1.0.tar.gz",
        )
    ]


def test_a_version_with_an_epoch_and_a_local_part_is_linked_as_it_is_written():
    page = pages.project_page("pkg", [Link("pkg-1.0+cpu.tar.gz", "1!1.0+cpu", f"sha256={SHA}")])

    assert read(page).found[0][0]["href"] == (
        f"../../packages/pkg/1!1.0+cpu/pkg-1.0+cpu.tar.gz#sha256={SHA}"
    )


def test_a_link_without_a_hash_has_no_fragment():
    page = pages.project_page("pkg", [Link("pkg-1.0.tar.gz", "1.0")])

    assert read(page).found[0][0] == {"href": "../../packages/pkg/1.0/pkg-1.0.tar.gz"}


def test_a_project_without_files_still_has_a_page():
    page = pages.project_page("pkg", [])

    assert read(page).found == []
    assert page.endswith(b"</html>\n")
    assert b"Links for pkg" in page


def test_the_root_page_links_each_project():
    page = pages.root_page(["django", "zope-interface"])

    assert read(page).found == [
        ({"href": "django/"}, "django"),
        ({"href": "zope-interface/"}, "zope-interface"),
    ]
    assert read(page).metas == {"pypi:repository-version": "1.0"}
    assert read(pages.root_page([])).found == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi/test_pages.py -q`
Expected: collection error, `cannot import name 'pages' from 'megooarti.repositories.pypi'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/pypi/pages.py`:

```python
"""PyPI index pages (PEP 503): the list of projects, and the files of one project.

Pure functions. Every link is relative, so a page is the same whatever address the
client used to reach the repository.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

CONTENT_TYPE = "text/html; charset=utf-8"
_HEAD = (
    "<!DOCTYPE html>\n<html>\n  <head>\n"
    '    <meta name="pypi:repository-version" content="1.0">\n'
    "    <title>{title}</title>\n  </head>\n  <body>\n    <h1>{title}</h1>\n"
)
_FOOT = "  </body>\n</html>\n"


@dataclass(frozen=True)
class Link:
    """One file on a project's page."""

    filename: str
    version: str
    digest: str = ""  # `sha256=<hex>`: what a client checks the download against
    requires_python: str | None = None


def _segment(text: str) -> str:
    """A version or a file name as it is written in an address. `+` and `!` stay."""
    return quote(text, safe="+!")


def head(title: str) -> bytes:
    return _HEAD.format(title=escape(title)).encode()


def foot() -> bytes:
    return _FOOT.encode()


def link_line(project: str, link: Link) -> bytes:
    """One file's line. `project` is in its normal form; the page is at `simple/<project>/`."""
    address = f"../../packages/{project}/{_segment(link.version)}/{_segment(link.filename)}"
    if link.digest:
        address += f"#{link.digest}"
    attributes = f' href="{escape(address)}"'
    if link.requires_python:
        attributes += f' data-requires-python="{escape(link.requires_python)}"'
    return f"    <a{attributes}>{escape(link.filename)}</a><br>\n".encode()


def project_page(project: str, links: Iterable[Link]) -> bytes:
    """The page of a project that is held whole in memory: a hosted repository's."""
    lines = [link_line(project, link) for link in links]
    return head(f"Links for {project}") + b"".join(lines) + foot()


def root_page(projects: Iterable[str]) -> bytes:
    """The list of projects. The page is at `simple/`."""
    lines = [
        f'    <a href="{escape(project)}/">{escape(project)}</a><br>\n' for project in projects
    ]
    return head("Simple index") + "".join(lines).encode() + foot()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/pypi -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/pypi/pages.py backend/tests/repositories/pypi/test_pages.py
git commit -m "feat(pypi): write the index pages of PEP 503"
```

---

### Task 5: The upload form

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`
- Create: `backend/src/megooarti/repositories/pypi/upload.py`
- Create: `backend/tests/repositories/pypi/conftest.py`
- Test: `backend/tests/repositories/pypi/test_upload.py`

**Interfaces:**
- Consumes: `names.is_valid_name`, `names.is_valid_segment`, `names.normalise`, `names.version_of`, `names.UPLOADABLE` (Task 3).
- Produces:
  - `upload.InvalidUpload` (its message says why), `upload.FIELD_LIMIT`, `upload.MAX_PARTS`.
  - `upload.Form(content_type: str)`: raises `InvalidUpload` unless it is `multipart/form-data` with a boundary. `feed(chunk: bytes) -> list[bytes]` returns pieces of the file; `finish()` raises if the form is cut short. Then `fields: dict[str, str]`, `filename: str | None`, `files: int`.
  - `upload.Declared(project, name, version, filename, summary, requires_python, digests)` and `upload.declared(fields, filename, files) -> Declared`, which raises `InvalidUpload`. `digests` maps `sha256` and `md5` to lower-case hex.
  - Test helpers in `tests/repositories/pypi/conftest.py`: `URL`, `BOUNDARY`, `CONTENT_TYPE`, `WHEEL`, `SDIST`, `create(db, name, *, hosted=None)`, `content_of(filename)`, `form_body(fields, file, *, extra=None, file_first=False)`, `upload_fields(name, version, data, **changes)`, `await upload(client, headers, filename, **changes)`, and the fixtures `index` and `root`.

- [ ] **Step 1: Write the test helpers and the failing tests**

`backend/tests/repositories/pypi/conftest.py`:

```python
import hashlib

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/pypi"
BOUNDARY = "megooarti-test-boundary-7MA4YWxkTrZu0gW"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"
WHEEL = "megooarti_greeter-1.0.0-py3-none-any.whl"
SDIST = "megooarti_greeter-1.0.0.tar.gz"


async def create(db, name: str, *, hosted: dict | None = None) -> Repository:
    """A hosted PyPI repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="pypi",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config={},
    )
    await db.commit()
    return repository


def content_of(filename: str) -> bytes:
    """Stand-in file bytes, different for every file name."""
    return f"PK\x03\x04 contents of {filename}".encode()


def _part(name: str, value, boundary: str) -> bytes:
    disposition = f'Content-Disposition: form-data; name="{name}"'
    if isinstance(value, tuple):  # a file: (file name, bytes)
        filename, value = value
        disposition += f'; filename="{filename}"\r\nContent-Type: application/octet-stream'
    data = value if isinstance(value, bytes) else str(value).encode()
    return f"--{boundary}\r\n{disposition}\r\n\r\n".encode() + data + b"\r\n"


def form_body(
    fields: dict,
    file: tuple[str, bytes] | None,
    *,
    extra: list[tuple[str, object]] | None = None,
    file_first: bool = False,
    boundary: str = BOUNDARY,
) -> bytes:
    """A multipart form as an upload client writes it: the fields, then the file."""
    parts = list(fields.items())
    if file is not None:
        parts.insert(0, ("content", file)) if file_first else parts.append(("content", file))
    parts.extend(extra or [])
    body = b"".join(_part(name, value, boundary) for name, value in parts)
    return body + f"--{boundary}--\r\n".encode()


def upload_fields(name: str, version: str, data: bytes, **changes) -> dict:
    """The fields twine sends with a file."""
    fields = {
        ":action": "file_upload",
        "protocol_version": "1",
        "metadata_version": "2.1",
        "name": name,
        "version": version,
        "filetype": "bdist_wheel",
        "pyversion": "py3",
        "sha256_digest": hashlib.sha256(data).hexdigest(),
        "md5_digest": hashlib.md5(data).hexdigest(),
        "blake2_256_digest": hashlib.blake2b(data, digest_size=32).hexdigest(),
    }
    fields.update(changes)
    return {key: value for key, value in fields.items() if value is not None}


async def upload(client, headers, filename: str, **changes):
    """Upload one file as twine does. The project and version are read from its name.

    `repository`, `data`, `name` and `version` can be given; anything else is a form field.
    """
    repository = changes.pop("repository", "pypi")
    data = changes.pop("data", None) or content_of(filename)
    stem = filename.removesuffix(".whl").removesuffix(".tar.gz").removesuffix(".zip")
    name = changes.pop("name", stem.split("-")[0])
    version = changes.pop("version", stem.split("-")[1])
    body = form_body(upload_fields(name, version, data, **changes), (filename, data))
    return await client.post(
        f"/repository/{repository}/",
        content=body,
        headers={**headers, "Content-Type": CONTENT_TYPE},
    )


@pytest.fixture
async def index(db) -> Repository:
    return await create(db, "pypi")


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

`backend/tests/repositories/pypi/test_upload.py`:

```python
import hashlib

import pytest

from megooarti.repositories.pypi import upload
from megooarti.repositories.pypi.upload import Declared, Form, InvalidUpload
from tests.repositories.pypi.conftest import BOUNDARY, CONTENT_TYPE, WHEEL, form_body

DATA = b"PK\x03\x04 not really a wheel " + bytes(range(256)) * 4
FIELDS = {
    ":action": "file_upload",
    "protocol_version": "1",
    "name": "Megooarti_Greeter",
    "version": "1.0.0",
    "filetype": "bdist_wheel",
    "summary": "Says hello",
    "requires_python": ">=3.9",
    "sha256_digest": hashlib.sha256(DATA).hexdigest(),
    "md5_digest": hashlib.md5(DATA).hexdigest(),
    "blake2_256_digest": "0" * 64,
    "description": "# A long README\n" * 200,
}
KEPT = {key: FIELDS[key] for key in FIELDS if key not in ("protocol_version", "filetype")}
KEPT = {
    key: value for key, value in KEPT.items() if key not in ("blake2_256_digest", "description")
}


def read(body: bytes, cuts: list[int] | None = None, content_type: str = CONTENT_TYPE):
    """Feed a body in pieces. Returns the form and the file's bytes."""
    form = Form(content_type)
    edges = [0, *sorted(cuts or []), len(body)]
    pieces = []
    for start, end in zip(edges, edges[1:], strict=False):
        pieces.extend(form.feed(body[start:end]))
    form.finish()
    return form, b"".join(pieces)


def test_a_form_gives_its_file_and_the_fields_that_are_used():
    form, data = read(form_body(FIELDS, (WHEEL, DATA)))

    assert data == DATA
    assert form.fields == KEPT
    assert (form.filename, form.files) == (WHEEL, 1)


def test_the_result_is_the_same_wherever_the_form_is_cut():
    body = form_body(FIELDS, (WHEEL, DATA))
    whole, data = read(body)

    for cut in range(len(body) + 1):
        form, pieces = read(body, [cut])
        assert (pieces, form.fields, form.filename) == (data, whole.fields, WHEEL), cut


def test_the_result_is_the_same_one_byte_at_a_time():
    body = form_body({**FIELDS, "description": "short"}, (WHEEL, DATA[:300]))

    form, data = read(body, list(range(1, len(body))))

    assert (data, form.fields) == (DATA[:300], KEPT)


def test_the_file_may_come_before_the_fields():
    body = form_body(FIELDS, (WHEEL, DATA), file_first=True)

    form, data = read(body)

    assert (data, form.fields, form.filename) == (DATA, KEPT, WHEEL)


def test_a_file_that_contains_the_boundary_text_is_not_cut_there():
    tricky = b"line one\r\n--" + BOUNDARY.encode()[:-1] + b"X\r\nline two\r\n"

    _, data = read(form_body(FIELDS, (WHEEL, tricky)))

    assert data == tricky


def test_a_field_that_is_not_used_can_be_any_length():
    huge = {**FIELDS, "description": "x" * (2 * 1024 * 1024)}

    form, data = read(form_body(huge, (WHEEL, DATA)))

    assert (data, form.fields) == (DATA, KEPT)


@pytest.mark.parametrize("name", ["name", "version", "summary", "requires_python", "sha256_digest"])
def test_a_field_that_is_used_has_a_limit(name):
    body = form_body({**FIELDS, name: "x" * (upload.FIELD_LIMIT + 1)}, (WHEEL, DATA))

    with pytest.raises(InvalidUpload, match=name):
        read(body)


def test_a_field_that_is_used_may_be_given_once():
    body = form_body(FIELDS, (WHEEL, DATA), extra=[("name", "another")])

    with pytest.raises(InvalidUpload, match="twice"):
        read(body)


def test_a_second_file_is_counted_and_not_read():
    body = form_body(FIELDS, (WHEEL, DATA), extra=[("content", ("other.whl", b"second"))])

    form, data = read(body)

    assert (data, form.files, form.filename) == (DATA, 2, WHEEL)


@pytest.mark.parametrize(
    "content_type",
    [
        "",
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "multipart/form-data; boundary=",
        "multipart/mixed; boundary=abc",
        "multipart/form-data; boundary=" + "b" * 500,
    ],
)
def test_what_is_not_a_multipart_form_is_refused_at_once(content_type):
    with pytest.raises(InvalidUpload):
        Form(content_type)


def test_a_form_cut_short_is_refused():
    body = form_body(FIELDS, (WHEEL, DATA))

    for length in (0, 10, len(body) // 2, len(body) - 3):
        with pytest.raises(InvalidUpload):
            read(body[:length])
    # The line break after the last boundary is not part of the form.
    assert read(body[:-2])[1] == DATA


@pytest.mark.parametrize("body", [b"not a form at all", b"\x00" * 100, b"--wrong-boundary\r\n\r\n"])
def test_a_body_that_is_not_the_form_it_says_is_refused(body):
    with pytest.raises(InvalidUpload):
        read(body)


def test_too_many_parts_are_refused(monkeypatch):
    monkeypatch.setattr(upload, "MAX_PARTS", 5)
    body = form_body(FIELDS, (WHEEL, DATA))

    with pytest.raises(InvalidUpload, match="parts"):
        read(body)


def test_a_field_that_is_not_text_is_refused():
    body = form_body({**FIELDS, "summary": b"\xff\xfe"}, (WHEEL, DATA))

    with pytest.raises(InvalidUpload, match="summary"):
        read(body)


def test_what_a_good_upload_declares():
    form, _ = read(form_body(FIELDS, (WHEEL, DATA)))

    assert upload.declared(form.fields, form.filename, form.files) == Declared(
        project="megooarti-greeter",
        name="Megooarti_Greeter",
        version="1.0.0",
        filename=WHEEL,
        summary="Says hello",
        requires_python=">=3.9",
        digests={"sha256": hashlib.sha256(DATA).hexdigest(), "md5": hashlib.md5(DATA).hexdigest()},
    )


def test_what_is_not_declared_is_left_out():
    fields = {":action": "file_upload", "name": "pkg", "version": "1.0", "summary": "  "}

    sent = upload.declared(fields, "pkg-1.0.tar.gz", 1)

    assert (sent.summary, sent.requires_python, sent.digests) == (None, None, {})


def test_digests_are_compared_in_lower_case():
    fields = {":action": "file_upload", "name": "pkg", "version": "1.0"}
    fields["sha256_digest"] = "ABCDEF" + "0" * 58

    assert upload.declared(fields, "pkg-1.0.zip", 1).digests == {"sha256": "abcdef" + "0" * 58}


GOOD = {":action": "file_upload", "name": "pkg", "version": "1.0"}


@pytest.mark.parametrize(
    ("fields", "filename", "files", "reason"),
    [
        ({**GOOD, ":action": "submit"}, "pkg-1.0.tar.gz", 1, "action"),
        ({"name": "pkg", "version": "1.0"}, "pkg-1.0.tar.gz", 1, "action"),
        (GOOD, None, 0, "one file"),
        (GOOD, "pkg-1.0.tar.gz", 2, "one file"),
        (GOOD, "", 1, "one file"),
        ({**GOOD, "name": "-pkg"}, "pkg-1.0.tar.gz", 1, "project name"),
        ({**GOOD, "name": ""}, "pkg-1.0.tar.gz", 1, "project name"),
        ({**GOOD, "version": "1.0/../.."}, "pkg-1.0.tar.gz", 1, "version"),
        ({**GOOD, "version": ".."}, "pkg-1.0.tar.gz", 1, "version"),
        ({**GOOD, "version": ""}, "pkg-1.0.tar.gz", 1, "version"),
        (GOOD, "pkg-1.0.exe", 1, "wheel or a source"),
        (GOOD, "pkg-1.0.tar.bz2", 1, "wheel or a source"),
        (GOOD, "../pkg-1.0.tar.gz", 1, "wheel or a source"),
        (GOOD, "pkg 1.0.tar.gz", 1, "wheel or a source"),
        (GOOD, "other-1.0.tar.gz", 1, "does not fit"),
        (GOOD, "pkg-1.0-py3-none.whl", 1, "does not fit"),
        ({**GOOD, "sha256_digest": "abc"}, "pkg-1.0.tar.gz", 1, "sha256_digest"),
        ({**GOOD, "md5_digest": "z" * 32}, "pkg-1.0.tar.gz", 1, "md5_digest"),
        ({**GOOD, "requires_python": ">=3.9\n<4"}, "pkg-1.0.tar.gz", 1, "requires_python"),
        ({**GOOD, "summary": "a\x00b"}, "pkg-1.0.tar.gz", 1, "summary"),
    ],
)
def test_what_a_bad_upload_is_refused_for(fields, filename, files, reason):
    with pytest.raises(InvalidUpload, match=reason):
        upload.declared(fields, filename, files)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi/test_upload.py -q`
Expected: collection error, `cannot import name 'upload' from 'megooarti.repositories.pypi'`.

- [ ] **Step 3: Add the dependency**

Run, in `backend/`:

```bash
uv add "python-multipart>=0.0.32"
```

Expected: `pyproject.toml` lists `python-multipart`, and `uv.lock` carries it. (`requirements.txt` is a local export that git ignores; nothing in the build reads it.)

- [ ] **Step 4: Implement**

`backend/src/megooarti/repositories/pypi/upload.py`:

```python
"""The upload form of the legacy PyPI API, read as it arrives.

`twine upload`, `uv publish` and `poetry publish` all send one file and its metadata as
`multipart/form-data`. The file can be gigabytes, so the form is never held in memory:
`Form.feed` hands the file's bytes on as they come, keeps the few fields that are used,
and reads past everything else. No database, no files.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from megooarti.repositories.pypi import names

# The fields that are used. A form carries dozens more, some of them very long.
_KEPT = frozenset(
    {":action", "name", "version", "summary", "requires_python", "sha256_digest", "md5_digest"}
)
_FILE = "content"
FIELD_LIMIT = 4096
MAX_PARTS = 10_000
# The digests a form may declare that a blob store computes, with their length in hex.
_DIGESTS = {"sha256_digest": ("sha256", 64), "md5_digest": ("md5", 32)}
_HEX = re.compile(r"[0-9a-f]+")


class InvalidUpload(Exception):
    """What was sent is not an upload this repository can take. The message says why."""


@dataclass(frozen=True)
class Declared:
    """What an upload says about its file, checked."""

    project: str  # the name in its normal form
    name: str  # the name as written
    version: str
    filename: str
    summary: str | None
    requires_python: str | None
    digests: dict[str, str] = field(default_factory=dict)  # algorithm -> lower-case hex


class Form:
    """Reads a form fed to it in pieces.

    `feed` returns the pieces of the file found so far. After `finish`, `fields` holds
    the fields that are used, `filename` the name the file was sent under, and `files`
    how many files there were.
    """

    def __init__(self, content_type: str) -> None:
        kind, options = parse_options_header(content_type)
        boundary = options.get(b"boundary", b"")
        if kind != b"multipart/form-data" or not boundary:
            raise InvalidUpload("it is not a multipart form")
        self.fields: dict[str, str] = {}
        self.filename: str | None = None
        self.files = 0
        self._parts = 0
        self._ended = False
        self._header_name = bytearray()
        self._header_text = bytearray()
        self._disposition = b""
        self._name: str | None = None  # the kept field being read, or None
        self._in_file = False
        self._value = bytearray()
        self._out: list[bytes] = []
        try:
            self._parser = MultipartParser(
                boundary,
                {
                    "on_part_begin": self._part_begin,
                    "on_header_field": self._header_field,
                    "on_header_value": self._header_value,
                    "on_header_end": self._header_end,
                    "on_headers_finished": self._headers_finished,
                    "on_part_data": self._part_data,
                    "on_part_end": self._part_end,
                    "on_end": self._end,
                },
            )
        except FormParserError:
            raise InvalidUpload("its boundary is not valid") from None

    def feed(self, chunk: bytes) -> list[bytes]:
        self._out = []
        try:
            self._parser.write(chunk)
        except FormParserError:
            raise InvalidUpload("it is not a well-formed multipart form") from None
        return self._out

    def finish(self) -> None:
        """Say that no more is coming. Raises InvalidUpload if the form is cut short."""
        try:
            self._parser.finalize()
        except FormParserError:
            raise InvalidUpload("the form is cut short") from None
        if not self._ended:
            raise InvalidUpload("the form is cut short")

    def _part_begin(self) -> None:
        self._parts += 1
        if self._parts > MAX_PARTS:
            raise InvalidUpload(f"it has more than {MAX_PARTS} parts")
        self._disposition = b""
        self._name = None
        self._in_file = False
        self._value.clear()

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_text += data[start:end]

    def _header_end(self) -> None:
        if bytes(self._header_name).lower() == b"content-disposition":
            self._disposition = bytes(self._header_text)
        self._header_name.clear()
        self._header_text.clear()

    def _headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        name = options.get(b"name", b"").decode("utf-8", "replace")
        if name == _FILE:
            self.files += 1
            self._in_file = self.files == 1  # a second file is counted, and read past
            if self._in_file:
                try:
                    self.filename = options.get(b"filename", b"").decode("utf-8")
                except UnicodeDecodeError:
                    raise InvalidUpload("the file's name is not valid text") from None
        elif name in _KEPT:
            if name in self.fields:
                raise InvalidUpload(f"it gives {name} twice")
            self._name = name

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if self._in_file:
            self._out.append(data[start:end])
        elif self._name is not None:
            self._value += data[start:end]
            if len(self._value) > FIELD_LIMIT:
                raise InvalidUpload(f"{self._name} is longer than {FIELD_LIMIT} bytes")

    def _part_end(self) -> None:
        if self._name is not None:
            try:
                self.fields[self._name] = self._value.decode("utf-8")
            except UnicodeDecodeError:
                raise InvalidUpload(f"{self._name} is not valid text") from None
        self._name = None
        self._in_file = False
        self._value.clear()

    def _end(self) -> None:
        self._ended = True


def _optional(fields: Mapping[str, str], name: str) -> str | None:
    value = fields.get(name, "").strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise InvalidUpload(f"{name} contains a control character")
    return value or None


def declared(fields: Mapping[str, str], filename: str | None, files: int) -> Declared:
    """Check what a form says about its file. Raises InvalidUpload."""
    if fields.get(":action") != "file_upload":
        raise InvalidUpload("its action is not file_upload")
    if files != 1 or not filename:
        raise InvalidUpload("it must carry exactly one file, as content")
    name = fields.get("name", "")
    if not names.is_valid_name(name):
        raise InvalidUpload("the project name is not valid")
    version = fields.get("version", "")
    if not names.is_valid_segment(version):
        raise InvalidUpload("the version is not valid")
    if not names.is_valid_segment(filename) or not filename.endswith(names.UPLOADABLE):
        raise InvalidUpload("the file is not a wheel or a source distribution")
    project = names.normalise(name)
    if names.version_of(project, filename) is None:
        raise InvalidUpload("the file's name does not fit the project")

    digests = {}
    for form_field, (algorithm, length) in _DIGESTS.items():
        digest = fields.get(form_field, "").strip().lower()
        if not digest:
            continue
        if len(digest) != length or not _HEX.fullmatch(digest):
            raise InvalidUpload(f"{form_field} is not a digest")
        digests[algorithm] = digest
    return Declared(
        project=project,
        name=name,
        version=version,
        filename=filename,
        summary=_optional(fields, "summary"),
        requires_python=_optional(fields, "requires_python"),
        digests=digests,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/pypi -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/megooarti/repositories/pypi/upload.py backend/tests/repositories/pypi
git commit -m "feat(pypi): read an upload form as it streams"
```

---

### Task 6: Hosted PyPI repositories

**Files:**
- Create: `backend/src/megooarti/repositories/pypi/format.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/repositories/pypi/test_hosted.py`

**Interfaces:**
- Consumes: `authenticate_secret` with `__token__` (Task 1); `context.package_files`, `context.store(..., attributes=, component_attributes=)` (Task 2); `names` (Task 3); `pages` (Task 4); `upload` and the test helpers (Task 5); `context.require_write`, `context.release`, `context.stage`, `context.discard`, `context.respond`, `context.respond_with`, `context.delete`, `context.package_names`.
- Produces:
  - `PypiFormat`, registered as `pypi`, offering `hosted`.
  - A file's own attributes are `{"pypi": {"requires_python": ...}}`; its component's are `{"pypi": {"name": ..., "version": ..., "summary": ...}}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/pypi/test_hosted.py`:

```python
import hashlib
from html.parser import HTMLParser

import pytest
from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.pypi.conftest import (
    CONTENT_TYPE,
    SDIST,
    URL,
    WHEEL,
    content_of,
    create,
    form_body,
    upload,
    upload_fields,
)

PAGE = f"{URL}/simple/megooarti-greeter/"
FILES = f"{URL}/packages/megooarti-greeter/1.0.0"


class Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[dict, str]] = []
        self._open: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open = dict(attrs)

    def handle_data(self, data):
        if self._open is not None:
            self.found.append((self._open, data))
            self._open = None


def links(response) -> list[tuple[dict, str]]:
    parser = Anchors()
    parser.feed(response.text)
    return parser.found


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def left_in_storage(settings) -> list[str]:
    """The files the blob store holds, temporary ones included."""
    store = settings.data_dir / "blobs" / "default"
    return [path.name for path in store.rglob("*") if path.is_file()] if store.exists() else []


async def test_an_uploaded_file_can_be_downloaded(client, index, root, db):
    uploaded = await upload(client, root, WHEEL, summary="Says hello", requires_python=">=3.9")

    fetched = await client.get(f"{FILES}/{WHEEL}", headers=root)
    part = await client.get(f"{FILES}/{WHEEL}", headers={**root, "Range": "bytes=0-3"})

    data = content_of(WHEEL)
    assert (uploaded.status_code, uploaded.content) == (200, b""), uploaded.text
    assert (fetched.status_code, fetched.content) == (200, data)
    assert fetched.headers["Content-Type"] == "application/octet-stream"
    assert fetched.headers["ETag"] == f'"{hashlib.sha256(data).hexdigest()}"'
    assert fetched.headers["Content-Disposition"].startswith(f'attachment; filename="{WHEEL}"')
    assert (part.status_code, part.content) == (206, data[:4])
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == (
        "",
        "megooarti-greeter",
        "1.0.0",
    )
    assert component.attributes == {
        "pypi": {"name": "megooarti_greeter", "version": "1.0.0", "summary": "Says hello"}
    }
    asset = await db.scalar(select(Asset))
    assert asset.path == f"packages/megooarti-greeter/1.0.0/{WHEEL}"
    assert asset.attributes == {"pypi": {"requires_python": ">=3.9"}}


async def test_the_project_page_lists_what_is_stored(client, index, root):
    await upload(client, root, WHEEL, requires_python=">=3.9")
    await upload(client, root, SDIST)
    await upload(client, root, "megooarti_greeter-1.1.0.tar.gz")
    await upload(client, root, "unrelated-9.0.tar.gz")

    page = await client.get(PAGE, headers=root)

    assert page.status_code == 200, page.text
    assert page.headers["Content-Type"] == "text/html; charset=utf-8"
    assert page.headers["Content-Security-Policy"] == "sandbox"
    assert page.headers["X-Content-Type-Options"] == "nosniff"

    def link(version: str, filename: str, **attributes) -> tuple[dict, str]:
        digest = hashlib.sha256(content_of(filename)).hexdigest()
        href = f"../../packages/megooarti-greeter/{version}/{filename}#sha256={digest}"
        return {"href": href, **attributes}, filename

    assert links(page) == [
        link("1.0.0", WHEEL, **{"data-requires-python": ">=3.9"}),
        link("1.0.0", SDIST),
        link("1.1.0", "megooarti_greeter-1.1.0.tar.gz"),
    ]


async def test_a_link_on_the_page_leads_to_the_file(client, index, root):
    await upload(client, root, WHEEL)
    page = await client.get(PAGE, headers=root)
    href = links(page)[0][0]["href"]

    fetched = await client.get(str(page.url.join(href)), headers=root)

    assert (fetched.status_code, fetched.content) == (200, content_of(WHEEL))


async def test_the_page_is_answered_like_any_content(client, index, root):
    await upload(client, root, WHEEL)
    first = await client.get(PAGE, headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(PAGE, headers={**root, "If-None-Match": etag})
    headed = await client.head(PAGE, headers=root)
    await upload(client, root, SDIST)
    changed = await client.get(PAGE, headers={**root, "If-None-Match": etag})

    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (headed.status_code, headed.content, headed.headers["ETag"]) == (200, b"", etag)
    assert (changed.status_code, len(links(changed))) == (200, 2)


async def test_every_spelling_of_a_name_is_one_project(client, index, root, db):
    await upload(client, root, WHEEL, name="Megooarti_Greeter")
    await upload(client, root, SDIST, name="megooarti.greeter")

    page = await client.get(PAGE, headers=root)

    assert [text for _, text in links(page)] == [WHEEL, SDIST]
    assert await count(db, Component) == 1


@pytest.mark.parametrize(
    ("asked", "location"),
    [
        ("simple", "simple/"),
        ("simple/megooarti-greeter", "megooarti-greeter/"),
        ("simple/Megooarti_Greeter", "megooarti-greeter/"),
        ("simple/Megooarti_Greeter/", "../megooarti-greeter/"),
        ("simple/megooarti.greeter/", "../megooarti-greeter/"),
    ],
)
async def test_a_page_has_one_address_and_the_others_lead_to_it(
    client, index, root, asked, location
):
    await upload(client, root, WHEEL)

    moved = await client.get(f"{URL}/{asked}", headers=root)
    followed = await client.get(f"{URL}/{asked}", headers=root, follow_redirects=True)

    assert (moved.status_code, moved.headers["Location"]) == (301, location)
    assert followed.status_code == 200
    assert followed.url.path in (f"{URL}/simple/", f"{URL}/simple/megooarti-greeter/")


async def test_the_root_index_lists_the_projects_held(client, index, root):
    empty = await client.get(f"{URL}/simple/", headers=root)
    await upload(client, root, "zope.interface-6.0.tar.gz")
    await upload(client, root, WHEEL)
    await upload(client, root, SDIST)

    listed = await client.get(f"{URL}/simple/", headers=root)

    assert (empty.status_code, links(empty)) == (200, [])
    assert links(listed) == [
        ({"href": "megooarti-greeter/"}, "megooarti-greeter"),
        ({"href": "zope-interface/"}, "zope-interface"),
    ]
    assert listed.headers["Content-Type"] == "text/html; charset=utf-8"


async def test_a_deleted_file_leaves_the_page_and_the_last_one_takes_the_project(
    client, index, root, db
):
    await upload(client, root, WHEEL)
    await upload(client, root, SDIST)

    removed = await client.delete(f"{FILES}/{WHEEL}", headers=root)
    after_one = await client.get(PAGE, headers=root)
    again = await client.delete(f"{FILES}/{WHEEL}", headers=root)
    await client.delete(f"{FILES}/{SDIST}", headers=root)
    after_all = await client.get(PAGE, headers=root)

    assert removed.status_code == 204
    assert [text for _, text in links(after_one)] == [SDIST]
    assert (again.status_code, error_code(again)) == (404, "not_found")
    assert (after_all.status_code, error_code(after_all)) == (404, "not_found")
    assert await count(db, Component) == 0


async def test_a_project_nobody_uploaded_is_not_found(client, index, root):
    response = await client.get(f"{URL}/simple/requests/", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


@pytest.mark.parametrize("field", ["sha256_digest", "md5_digest"])
async def test_a_file_that_is_not_the_one_declared_is_refused(
    client, index, root, db, settings, field
):
    wrong = hashlib.new(field.partition("_")[0], b"another file").hexdigest()

    response = await upload(client, root, WHEEL, **{field: wrong})

    assert (response.status_code, error_code(response)) == (400, "checksum_mismatch")
    assert await count(db, Asset) == 0
    assert left_in_storage(settings) == []


async def test_a_digest_the_store_does_not_compute_is_not_checked(client, index, root):
    response = await upload(client, root, WHEEL, blake2_256_digest="0" * 64)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {":action": "submit"},
        {":action": None},
        {"name": "-not-a-name-"},
        {"name": "another-project"},
        {"version": "../.."},
        {"version": None},
        {"sha256_digest": "not hex"},
        {"requires_python": ">=3.9\n<4"},
    ],
    ids=lambda changes: next(iter(changes)) + "=" + str(next(iter(changes.values())))[:12],
)
async def test_an_upload_that_is_not_acceptable_stores_nothing(
    client, index, root, db, settings, changes
):
    response = await upload(client, root, WHEEL, **changes)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert await count(db, Asset) == 0
    assert left_in_storage(settings) == []


@pytest.mark.parametrize(
    "filename",
    ["megooarti_greeter-1.0.0.exe", "megooarti_greeter-1.0.0-py3-none.whl", "x y-1.0.0.tar.gz"],
)
async def test_a_file_of_a_kind_that_is_not_taken_is_refused(
    client, index, root, db, settings, filename
):
    response = await upload(client, root, filename, name="megooarti-greeter", version="1.0.0")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert left_in_storage(settings) == []


async def test_a_body_that_is_not_an_upload_form_is_refused(client, index, root, db, settings):
    data = content_of(WHEEL)
    whole = form_body(upload_fields("megooarti-greeter", "1.0.0", data), (WHEEL, data))
    no_file = form_body(upload_fields("megooarti-greeter", "1.0.0", data), None)
    two_files = form_body(
        upload_fields("megooarti-greeter", "1.0.0", data),
        (WHEEL, data),
        extra=[("content", (SDIST, b"another"))],
    )
    form = {**root, "Content-Type": CONTENT_TYPE}
    sent = [
        await client.post(f"{URL}/", json={"name": "megooarti-greeter"}, headers=root),
        await client.post(f"{URL}/", content=whole, headers=root),  # no content type
        await client.post(f"{URL}/", content=whole[: len(whole) // 2], headers=form),
        await client.post(f"{URL}/", content=b"", headers=form),
        await client.post(f"{URL}/", content=no_file, headers=form),
        await client.post(f"{URL}/", content=two_files, headers=form),
    ]

    for response in sent:
        assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert await count(db, Asset) == 0
    assert left_in_storage(settings) == []


async def test_a_large_file_arrives_whole(client, index, root):
    data = bytes(range(256)) * 4096 * 5  # 5 MiB, sent in many pieces
    body = form_body(upload_fields("megooarti-greeter", "1.0.0", data), (WHEEL, data))

    async def pieces():
        for start in range(0, len(body), 65_521):
            yield body[start : start + 65_521]

    uploaded = await client.post(
        f"{URL}/", content=pieces(), headers={**root, "Content-Type": CONTENT_TYPE}
    )
    fetched = await client.get(f"{FILES}/{WHEEL}", headers=root)

    assert uploaded.status_code == 200, uploaded.text
    assert hashlib.sha256(fetched.content).hexdigest() == hashlib.sha256(data).hexdigest()


async def test_uploading_a_file_again_replaces_it_unless_the_policy_forbids(client, db, root):
    await create(db, "pypi")
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    for repository in ("pypi", "once"):
        await upload(client, root, WHEEL, repository=repository, summary="first")

    replaced = await upload(client, root, WHEEL, data=b"rebuilt", summary="second")
    refused = await upload(client, root, WHEEL, repository="once", data=b"rebuilt")
    another = await upload(client, root, SDIST, repository="once", summary="third")
    page = await client.get(PAGE, headers=root)
    kept = await client.get(
        f"/repository/once/packages/megooarti-greeter/1.0.0/{WHEEL}", headers=root
    )

    assert replaced.status_code == 200
    assert links(page)[0][0]["href"].endswith(f"#sha256={hashlib.sha256(b'rebuilt').hexdigest()}")
    kept_about = [
        held["pypi"]["summary"] for held in await db.scalars(select(Component.attributes))
    ]
    assert sorted(kept_about) == ["second", "third"]  # the release's, from the last upload
    # What `twine upload --skip-existing` looks for.
    assert (refused.status_code, error_code(refused)) == (409, "redeploy_disabled")
    assert another.status_code == 200  # a new file of the same version is not a redeploy
    assert kept.content == content_of(WHEEL)


async def test_a_read_only_repository_refuses_before_reading_the_file(client, db, root, settings):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await upload(client, root, WHEEL, repository="frozen")

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")
    assert left_in_storage(settings) == []


async def test_each_change_needs_its_own_permission(client, index, root, make_user, db):
    for action in ("read", "add", "edit", "delete"):
        permissions = [f"repository:pypi:pypi:{action}"]
        await roles.create_role(db, f"only-{action}", "", permissions, [])
    await db.commit()
    for action in ("read", "add", "edit", "delete"):
        await make_user(f"{action}er", roles=[f"only-{action}"])
    reader, adder, editor, deleter = (
        basic(f"{action}er", PASSWORD) for action in ("read", "add", "edit", "delete")
    )

    by_reader = await upload(client, reader, WHEEL)
    by_deleter = await upload(client, deleter, WHEEL)
    by_adder = await upload(client, adder, WHEEL)
    adder_again = await upload(client, adder, WHEEL, data=b"rebuilt")
    by_editor = await upload(client, editor, WHEEL, data=b"rebuilt")
    editor_new = await upload(client, editor, SDIST)
    page = await client.get(PAGE, headers=reader)
    unreadable = await client.get(PAGE, headers=adder)
    not_deleted = await client.delete(f"{FILES}/{WHEEL}", headers=editor)
    deleted = await client.delete(f"{FILES}/{WHEEL}", headers=deleter)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert (by_deleter.status_code, error_code(by_deleter)) == (403, "forbidden")
    assert by_adder.status_code == 200
    assert (adder_again.status_code, error_code(adder_again)) == (403, "forbidden")
    assert by_editor.status_code == 200
    assert (editor_new.status_code, error_code(editor_new)) == (403, "forbidden")
    assert page.status_code == 200
    assert (unreadable.status_code, error_code(unreadable)) == (403, "forbidden")
    assert (not_deleted.status_code, error_code(not_deleted)) == (403, "forbidden")
    assert deleted.status_code == 204


async def test_without_credentials_there_is_a_basic_challenge(client, index):
    data = content_of(WHEEL)
    body = form_body(upload_fields("megooarti-greeter", "1.0.0", data), (WHEEL, data))

    uploaded = await client.post(f"{URL}/", content=body, headers={"Content-Type": CONTENT_TYPE})
    page = await client.get(PAGE)

    for response in (uploaded, page):
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
        assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_a_token_is_accepted_the_way_python_tools_send_it(
    client, index, make_user, make_token
):
    owner = await make_user("dana", roles=["admin"])
    token = await make_token(owner)

    uploaded = await upload(client, basic("__token__", token), WHEEL)
    page = await client.get(PAGE, headers=basic("__token__", token))
    refused = await upload(client, basic("__token__", PASSWORD), SDIST)

    assert (uploaded.status_code, page.status_code) == (200, 200)
    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


@pytest.mark.parametrize(
    ("method", "path", "status", "allow"),
    [
        ("GET", "", 405, "POST"),
        ("PUT", "", 405, "POST"),
        ("DELETE", "", 405, "POST"),
        ("POST", "simple/", 405, "GET, HEAD"),
        ("DELETE", "simple/megooarti-greeter/", 405, "GET, HEAD"),
        ("PUT", f"packages/megooarti-greeter/1.0.0/{WHEEL}", 405, "GET, HEAD, DELETE"),
        ("POST", f"packages/megooarti-greeter/1.0.0/{WHEEL}", 405, "GET, HEAD, DELETE"),
        ("GET", f"packages/megooarti-greeter/1.0.0/{WHEEL}.metadata", 404, None),
        ("GET", "pypi/megooarti-greeter/json", 404, None),
        ("GET", "simple/megooarti-greeter/index.html", 404, None),
        ("GET", "packages/Megooarti_Greeter/1.0.0/x.whl", 404, None),
        ("POST", "legacy/", 404, None),
    ],
)
async def test_what_an_address_does_not_do(client, index, root, method, path, status, allow):
    await upload(client, root, WHEEL)

    response = await client.request(method, f"{URL}/{path}", headers=root)

    assert response.status_code == status
    assert error_code(response) == ("method_not_allowed" if status == 405 else "not_found")
    assert response.headers.get("Allow") == allow


async def test_what_a_file_declares_cannot_break_the_page(client, index, root):
    hostile = '">3"><script>alert(1)</script>'
    await upload(client, root, WHEEL, requires_python=hostile)

    page = await client.get(PAGE, headers=root)

    assert "<script>" not in page.text
    assert links(page)[0][0]["data-requires-python"] == hostile
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi -q`
Expected: every test in `test_hosted.py` fails or errors: a `pypi` repository cannot be created, because the format is unknown. The tests of Tasks 3 to 5 pass.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/pypi/format.py`:

```python
"""The PyPI format: an index that twine uploads to and pip, uv and Poetry install from.

This is the only PyPI module that touches the repository context. What a path means,
whether an upload is acceptable and what a page says come from the pure functions
beside it.

A project's page is generated on each request from the files stored, so it is right
after a delete and after two uploads at once. An upload goes to the blob store as it
arrives: it is never held in memory.
"""

import hashlib
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.pypi import names, pages, upload

_FILE = "application/octet-stream"
# Where what an upload declares is kept among its component's attributes.
_DECLARED = "pypi"
# The most projects a root index lists. Installers never ask for it.
ROOT_LIMIT = 100_000
_PROTECTIVE = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}


def _not_found(message: str = "Nothing is served at this address.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405,
        "method_not_allowed",
        f"This address accepts {allowed}.",
        headers={"Allow": allowed},
    )


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The upload cannot be accepted: {reason}.")


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


def _redirect(location: str) -> Response:
    """Send the client to the one address a page has. `location` is relative."""
    return Response(status_code=301, headers={"Location": location, **_PROTECTIVE})


def _page(context: RepositoryContext, request: Request, data: bytes) -> Response:
    """The answer to a request for an index page that was built for it."""
    return context.respond_with(
        data,
        request,
        filename="index.html",
        content_type=pages.CONTENT_TYPE,
        last_modified=utcnow(),
        etag=hashlib.sha256(data).hexdigest(),
    )


# --- Reading -------------------------------------------------------------------------


async def _root_index(context: RepositoryContext, request: Request) -> Response:
    found, _ = await context.package_names("", limit=ROOT_LIMIT, offset=0)
    await context.release()  # writing the page needs no connection
    return _page(context, request, pages.root_page(name for _, name in found))


async def _project_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A hosted project's page, from the files stored. `project` is in its normal form."""
    files = await context.package_files("", project)
    if not files:
        raise _not_found("No such project.")
    await context.release()  # writing the page needs no connection
    links = [
        pages.Link(
            filename=held.path.rpartition("/")[2],
            version=held.version,
            digest=f"sha256={held.sha256}",
            requires_python=(held.attributes.get(_DECLARED) or {}).get("requires_python"),
        )
        for held in files
    ]
    return _page(context, request, pages.project_page(project, links))


# --- Uploading -----------------------------------------------------------------------


async def _upload(context: RepositoryContext, request: Request) -> Response:
    """Take one file and what the client says about it, as twine sends them."""
    # Refused before the body is read; the facade checks again when the file is stored.
    context.require_write()
    try:
        form = upload.Form(request.headers.get("Content-Type", ""))
    except upload.InvalidUpload as error:
        raise _invalid(error) from None
    await context.release()  # the body needs no connection

    async def file_bytes() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            for piece in form.feed(chunk):
                yield piece
        form.finish()

    try:
        staged = await context.stage(file_bytes())
    except upload.InvalidUpload as error:
        raise _invalid(error) from None
    try:
        sent = upload.declared(form.fields, form.filename, form.files)
    except upload.InvalidUpload as error:
        await context.discard(staged)
        raise _invalid(error) from None
    wrong = [name for name, digest in sent.digests.items() if getattr(staged, name) != digest]
    if wrong:
        await context.discard(staged)
        raise ApiError(400, "checksum_mismatch", f"The {wrong[0]} digest does not match the file.")

    release = {"name": sent.name, "version": sent.version, "summary": sent.summary}
    # The facade checks `add` or `edit` and the deployment policy, under the path's lock.
    await context.store(
        names.file_path(sent.project, sent.version, sent.filename),
        staged,
        content_type=_FILE,
        # A page says what each file requires, so that is kept with the file.
        attributes={_DECLARED: {"requires_python": sent.requires_python}},
        component_attributes={_DECLARED: release},
    )
    return Response(status_code=200, headers=_PROTECTIVE)


async def _file(context: RepositoryContext, request: Request, path: str) -> Response:
    if _is_read(request):
        return await context.respond(path, request)
    if request.method != "DELETE":
        # A file arrives in an upload form, with what it declares, never on its own.
        raise _not_allowed("GET, HEAD, DELETE")
    if not await context.delete(path):
        raise _not_found("No such file.")
    return Response(status_code=204)


def _canonical(parsed: names.PypiPath) -> Response | None:
    """The redirect to an index page's one address, or None if this is it.

    Links in a page are relative, so a page served at another spelling of its
    address would point nowhere.
    """
    if parsed.kind == "index":
        return None if parsed.slash else _redirect("simple/")
    project = names.normalise(parsed.project)
    if parsed.slash:
        return None if parsed.project == project else _redirect(f"../{project}/")
    return _redirect(f"{project}/")


class PypiFormat(Format):
    name = "pypi"
    # Proxy and group repositories need PyPI's own handling of index pages.
    types = frozenset({"hosted"})

    def describe_component(self, path: str) -> ComponentKey | None:
        """A file belongs to its project and version. Nothing else is part of one."""
        parsed = names.classify(path)
        if parsed.kind != "file":
            return None
        return ComponentKey("", parsed.project, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        return _FILE if names.classify(path).kind == "file" else declared

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = names.classify(path)
        if parsed.kind == "repository":
            if request.method != "POST":
                raise _not_allowed("POST")
            return await _upload(context, request)
        if parsed.kind in ("index", "page"):
            if not _is_read(request):
                raise _not_allowed("GET, HEAD")
            moved = _canonical(parsed)
            if moved is not None:
                return moved
            if parsed.kind == "index":
                return await _root_index(context, request)
            return await _project_page(context, request, parsed.project)
        if parsed.kind == "file":
            return await _file(context, request, path)
        raise _not_found()


register(PypiFormat())
```

In `backend/src/megooarti/main.py`:

After

```python
from megooarti.repositories.npm import format as _npm_format  # noqa: F401  (registers it)
```

add

```python
from megooarti.repositories.pypi import format as _pypi_format  # noqa: F401  (registers it)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories tests/security -q`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/pypi/format.py backend/src/megooarti/main.py backend/tests/repositories/pypi/test_hosted.py
git commit -m "feat(pypi): hosted PyPI repositories with uploads and generated index pages"
```

---

### Task 7: twine, uv and pip; documentation

**Files:**
- Create: `backend/tests/test_pypi_client.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: hosted PyPI; `tests/containers.py` (`HTTP_PORT`, `PROJECT`, `call`); the `stack` and `administrator` fixtures.
- Produces: a Docker-marked test that drives the real `twine`, `uv` and `pip` against the built image.

This test runs only with `pytest -m docker`. It needs a Docker daemon and internet access: the Python image, and twine and uv from pypi.org.

- [ ] **Step 1: Write the real-client test**

`backend/tests/test_pypi_client.py`:

```python
"""Python's own packaging tools against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to
pull the Python image, and to install twine and uv into it from pypi.org. Everything
those tools then upload or install goes to MegooArti.
"""

import subprocess
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "python:3.13-slim"
NETWORK = f"{PROJECT}_default"
HOSTED = "pypi-hosted"
# What a publishing account gets: everything on PyPI repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "uploads-and-installs-python-packages"
PROJECT_NAME = "megooarti-greeter"

# Writes a wheel and a source distribution of one small package into dist/, with the
# standard library only: `make_dist.py <version>`.
MAKE_DIST = """
import base64, hashlib, io, sys, tarfile, zipfile
from pathlib import Path

version = sys.argv[1]
name, module = "megooarti-greeter", "megooarti_greeter"
metadata = (
    "Metadata-Version: 2.1\\n"
    f"Name: {name}\\nVersion: {version}\\nSummary: Says hello\\nRequires-Python: >=3.9\\n"
)
code = f'def hello():\\n    return "hello from {name} {version}"\\n'
dist = Path("dist")
dist.mkdir(exist_ok=True)

info = f"{module}-{version}.dist-info"
files = {
    f"{module}/__init__.py": code,
    f"{info}/METADATA": metadata,
    f"{info}/WHEEL": (
        "Wheel-Version: 1.0\\nGenerator: megooarti\\n"
        "Root-Is-Purelib: true\\nTag: py3-none-any\\n"
    ),
}
record = ""
for path, text in files.items():
    digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=")
    record += f"{path},sha256={digest.decode()},{len(text.encode())}\\n"
files[f"{info}/RECORD"] = record + f"{info}/RECORD,,\\n"
with zipfile.ZipFile(dist / f"{module}-{version}-py3-none-any.whl", "w") as wheel:
    for path, text in files.items():
        wheel.writestr(path, text)

project = (
    '[build-system]\\nrequires = ["setuptools"]\\nbuild-backend = "setuptools.build_meta"\\n'
    f'[project]\\nname = "{name}"\\nversion = "{version}"\\n'
)
sources = {"PKG-INFO": metadata, "pyproject.toml": project, f"{module}/__init__.py": code}
with tarfile.open(dist / f"{module}-{version}.tar.gz", "w:gz") as sdist:
    for path, text in sources.items():
        entry = tarfile.TarInfo(f"{module}-{version}/{path}")
        entry.size = len(text.encode())
        sdist.addfile(entry, io.BytesIO(text.encode()))
"""


def inside(repository: str) -> str:
    """A repository's address as a container on the Compose network reaches it."""
    return f"http://backend:8000/repository/{repository}/"


def python(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Python image, in a copy of `directory`, beside the stack.

    Every run is a new container, so every tool starts with an empty cache.
    """
    setup = "cp -r /src /work && cd /work && export PIP_DISABLE_PIP_VERSION_CHECK=1"
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


# A shell function for a script that goes on after a failure: `command; report <step>`
# prints the command's exit code on a line of its own.
REPORT = 'report() { code=$?; printf \'\\n%s=%s\\n\' "$1" "$code"; }'


def exits(result: subprocess.CompletedProcess[str]) -> dict[str, int]:
    """The exit codes a script reported with `report <step>`."""
    lines = (line.partition("=") for line in result.stdout.splitlines())
    return {step: int(code) for step, _, code in lines if code.isdigit() and " " not in step}


def fetch(path: str, username: str = USERNAME, secret: str = PASSWORD) -> tuple[int, str]:
    """A GET to the hosted repository from outside: (status, body as text)."""
    credentials = b64encode(f"{username}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/{path}",
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, ""


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted PyPI repository, a publishing account, and an API token of that account."""
    repository = {
        "name": HOSTED,
        "format": "pypi",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    role = {"name": "pypi-publishers", "permissions": ["repository:pypi"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["pypi-publishers"],
        "must_change_password": False,
    }
    for path, body in (("/repositories", repository), ("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer

    status, headers, session = call(
        "POST", "/auth/login", {"username": USERNAME, "password": PASSWORD}
    )
    assert status == 200, session
    signed_in = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }
    status, _, created = call("POST", "/me/tokens", {"name": "publishing"}, signed_in)
    assert status == 201, created
    return created["token"]


def test_twine_and_uv_publish_and_pip_installs(token, tmp_path):
    work = tmp_path / "pypi"
    work.mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    index = f"http://{USERNAME}:{PASSWORD}@backend:8000/repository/{HOSTED}/simple/"
    token_index = f"http://__token__:{token}@backend:8000/repository/{HOSTED}/simple/"

    # twine uploads a wheel and a source distribution with a user name and a password.
    # A second upload of the same files is refused.
    twine = (
        f"twine upload --non-interactive --disable-progress-bar --repository-url {inside(HOSTED)}"
    )
    account = f"-u {USERNAME} -p {PASSWORD}"
    published = python(
        work,
        f"{REPORT}; pip install --quiet twine && python make_dist.py 1.0.0"
        f" && {twine} {account} dist/*; report first"
        f"; {twine} {account} dist/*; report again",
    )
    codes = exits(published)
    assert codes.get("first") == 0, said(published)
    assert codes.get("again") not in (0, None), "uploaded twice despite disable_redeploy"

    # uv publishes the next version with nothing but a token, as the user `__token__`.
    # Told where the index is, it passes over files that are already there. It does not
    # send the token to the index by itself, so the address carries it.
    uv = f"uv publish --publish-url {inside(HOSTED)} --token {token}"
    by_token = python(
        work,
        f"{REPORT}; pip install --quiet uv && python make_dist.py 1.1.0"
        f" && {uv} dist/*; report first"
        f"; {uv} dist/*; report again"
        f"; {uv} --check-url {token_index} dist/*; report checked",
    )
    codes = exits(by_token)
    assert codes.get("first") == 0, said(by_token)
    assert codes.get("again") not in (0, None), "uploaded twice despite disable_redeploy"
    assert codes.get("checked") == 0, said(by_token)

    # What the index says now.
    status, root_index = fetch("simple/")
    assert (status, f'<a href="{PROJECT_NAME}/">' in root_index) == (200, True)
    status, page = fetch(f"simple/{PROJECT_NAME}/", "__token__", token)
    assert status == 200
    for version in ("1.0.0", "1.1.0"):
        assert f">megooarti_greeter-{version}-py3-none-any.whl</a>" in page
        assert f">megooarti_greeter-{version}.tar.gz</a>" in page
    assert page.count('data-requires-python="&gt;=3.9"') == 4
    assert page.count("#sha256=") == 4

    # pip installs the newest version from an empty cache, then one it is asked for.
    pip = f"pip install --quiet --index-url {index} --trusted-host backend"
    run_it = 'python -c "import megooarti_greeter; print(megooarti_greeter.hello())"'
    installed = python(
        work, f"{pip} {PROJECT_NAME} && {run_it} && {pip} {PROJECT_NAME}==1.0.0 && {run_it}"
    )
    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-2:] == [
        f"hello from {PROJECT_NAME} 1.1.0",
        f"hello from {PROJECT_NAME} 1.0.0",
    ]

    # uv installs it too, with the token.
    with_uv = python(
        work,
        "pip install --quiet uv"
        f" && uv pip install --system --index-url {token_index} {PROJECT_NAME}==1.1.0"
        f" && {run_it}",
    )
    assert with_uv.returncode == 0, said(with_uv)
    assert with_uv.stdout.splitlines()[-1] == f"hello from {PROJECT_NAME} 1.1.0"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_pypi_client.py -q`
Expected: 1 passed. This builds the image from the working tree, so it is the first run of the real tools against this plan's code. If a tool fails, the assertion message carries the end of its output.

- [ ] **Step 3: Document PyPI repositories**

In `README.md`:

Replace

```markdown
- **Personal API tokens** (`mga_…`) are created under `/api/v1/me/tokens` while signed
  in with a password. Use one as a bearer token, or as the password in HTTP Basic. A
  token can be limited to a list of patterns and can expire.
```

with

```markdown
- **Personal API tokens** (`mga_…`) are created under `/api/v1/me/tokens` while signed
  in with a password. Use one as a bearer token, or as the password in HTTP Basic,
  with your user name or with the name `__token__`, which is how Python's tools send
  a token. A token can be limited to a list of patterns and can expire.
```

Replace

```markdown
`raw` (arbitrary files by path), `maven` and `npm`.
```

with

```markdown
`raw` (arbitrary files by path), `maven`, `npm` and `pypi` (hosted repositories only,
for now).
```

Replace

```markdown
Reading through a group needs `read` on the group only, for example
`repository:npm:npm-public:read`.

## Health endpoints
```

with

````markdown
Reading through a group needs `read` on the group only, for example
`repository:npm:npm-public:read`.

### PyPI repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-hosted", "format": "pypi", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"}
}' http://localhost:8000/api/v1/repositories
```

Upload to the repository's address, with the slash at its end, and install from
`simple/` beneath it:

```bash
twine upload --repository-url https://repo.example.com/repository/pypi-hosted/ \
  -u __token__ -p "$MEGOOARTI_TOKEN" dist/*
uv publish --publish-url https://repo.example.com/repository/pypi-hosted/ --token "$MEGOOARTI_TOKEN"

pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-hosted/simple/ my-package
```

- **Credentials** are HTTP Basic: a user name and password, a user name and a token, or
  `__token__` and a token.
- **A project's page is generated** on every request from the files stored, so it is
  right after a delete and after two uploads at the same moment. It is the HTML index
  of PEP 503, with each file's `sha256` and the Python versions it requires.
- **Every spelling of a name is one project**: `My_Package`, `my.package` and
  `my-package` are stored and listed as `my-package`.
- **An upload is streamed to disk** as it arrives, whatever its size, and is checked
  against the `sha256` and `md5` digests the client sends. Wheels (`.whl`) and source
  distributions (`.tar.gz`, `.zip`) are taken; the file's name must fit its project.
  `poetry publish` sends the same request as twine.
- **Uploading a file again** follows the deployment policy. With `disable_redeploy` it
  answers `409`. `uv publish --check-url <index address>` passes over files that are
  already there; give that address its credentials, because uv does not send the
  token to it. twine's `--skip-existing` works only with pypi.org.
- **Permissions.** Uploading a new file needs `add`, replacing one `edit`, and deleting
  one (`DELETE` on its address under `packages/`) `delete`.
- Signatures sent with an upload are not kept. The JSON index (PEP 691), metadata
  files (PEP 658) and yanking are not available yet; pip, uv and Poetry do not need
  them.
- Proxy and group PyPI repositories are not available yet.

## Health endpoints
````

- [ ] **Step 4: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

Run: `uv run pytest -m docker -q`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pypi_client.py README.md
git commit -m "test(pypi): upload with twine and uv, install with pip and uv; document PyPI repositories"
```
