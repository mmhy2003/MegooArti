# NuGet Symbol Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A NuGet repository is a symbol server: the portable PDBs of the symbol packages pushed to it are served at the keys debuggers ask for, so that Visual Studio and `dotnet-symbol` step into an organisation's own packages; a proxy passes such requests on to a public symbol server, and a group asks its members.

**Architecture:** A pure module, `nuget/symbols.py`, reads a portable PDB (`BSJB`, then its `#Pdb` stream's id) into its SSQP key and its checksum. `nuget/symbol_server.py` keeps each PDB of a pushed or uploaded `.snupkg` at its key as a file of the version, serves it to a debugger that names its checksum, and for a proxy with a `symbol_url` asks that server with the debugger's `SymbolChecksum` (the proxy engine gains `Source.headers`, sent with a download). A group asks its members as for any file. HTTP Basic with no user name takes an API token, as `dotnet-symbol` sends one.

**Tech Stack:** Python 3.13, FastAPI; pytest with PDBs the tests write and the in-process stand-in remote; the .NET SDKs 10 and 8 with `dotnet-symbol` 10.0 for the real-client test.

**Spec:** [docs/superpowers/specs/2026-10-15-nuget-design.md](../specs/2026-10-15-nuget-design.md), sections 8, 9 (a symbol package's bounds), 10 (`dotnet-symbol`), 11 (the risk of the checksum) and the row of plan 13f in section 12, with what plans 13a to 13e settled.

## Decisions this plan settles

Task 5 writes these into the spec's section 4, as "Settled while building plan 13f", and mends section 8's key. S1's key and checksum were seen as `dotnet-symbol` asks nuget.org's symbol server for Serilog's PDB, and checked against that PDB.

| # | Decision | Reason |
| --- | --- | --- |
| S2 | Every `.pdb` of a symbol package's zip is read as it is pushed or uploaded, staged one at a time (at most 1,000, each at most 256 MiB). One that is not a portable PDB refuses the symbol package with `400 invalid_package`, which names it, and nothing of it is kept. Each PDB is a file of the package's version, with its checksum among its attributes. A symbol package pushed again (under `allow_redeploy`) keeps only its own PDBs; deleting a symbol package deletes its PDBs, and deleting a version every file of it (D4). | 8, and one record of what a PDB is, read once (E1). |
| S3 | `SymbolChecksum` names SHA-256 checksums (`SHA256:<hex>`, `;` between them); a PDB is served if one of them is its own, or if none is named; else `404`. | As nuget.org's symbol server answers; a debugger that names none still gets what it asks for by its key. |
| S4 | A proxy with a `symbol_url` asks `<symbol_url>/<name>/<key>/<name>` for a PDB it does not keep, sending the debugger's `SymbolChecksum` (the proxy engine sends a source's own headers with a download, `proxy.Source.headers`); what it is not given is not remembered as missing. A PDB it keeps has its checksum read from it, and a debugger that names another is answered `404` without asking. A proxy without a `symbol_url` has no symbols. A V2 proxy may have one too. | 8; a server that has no file for one checksum may have it for another. |
| S5 | HTTP Basic with no user name and an API token as the password is the token's owner, as with `__token__`; with anything else, a failed attempt counted against the address. | `dotnet-symbol --authenticated-server-path <token>` sends `:<token>`, as Azure DevOps's clients do. |
| S6 | A group asks its members in order for a PDB, as the group engine asks for any file (Y10's files a group passes on, and a PDB). | 8. |
| S7 | A repository's setup has a `Symbols` snippet: the Visual Studio setting, and `dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" <address>symbols/`. | 8: the setup snippet says so. |
| S8 | The `dotnet` test installs `dotnet-symbol` 10.0.750501 through the proxy of nuget.org, and fetches the PDB of each SDK's package for its DLL from the hosted repository and through the group: the bytes its symbol package has. | Section 10's `dotnet-symbol`. |"""

## Global Constraints

- **What is read of a symbol package is bounded** (section 9): its PDBs at 1,000, and each at 256 MiB; the zip is read from its directory, and a PDB is inflated to its bound.
- **A format never touches a table or a file**: a PDB is kept with `context.store`, read with `context.get` and `context.respond`, and fetched with `proxy.ensure_cached`.
- **What is asked of a remote goes with its credential only to its own origin**: a proxy's symbol server is asked as any address its content names (`proxy.Source`).
- **Every test of a stack is marked `docker`.** The `dotnet` test installs `dotnet-symbol` through the proxy of nuget.org.
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **PDBs as compilers write them**: a PDB of hundreds of megabytes, two PDBs of one name in two frameworks' folders, a `.pdb` in a folder other than `lib/`, an embedded PDB, deterministic builds that give two versions one PDB id.
2. **Two versions with one key**: a PDB already kept for another version, under `disable_redeploy`, and what a push of the second version's symbol package is then answered.
3. **What a debugger sends**: `SymbolChecksum` with several checksums, in capitals, with SHA-1 beside SHA-256; Visual Studio's own requests, a HEAD before a GET, a key in other cases.
4. **A proxy's symbol server**: nuget.org's answer to a checksum it does not have (`404`, or another code), its redirects, a kept PDB later asked for with no checksum, a proxy whose `symbol_url` changes.
5. **A token with no user name**: what is counted against the address when the password is not a token, and an empty name with an empty password, as `choco` sends one without credentials.

---

### Task 1: What a portable PDB is

**Files:**
- Create: `backend/src/megooarti/repositories/nuget/symbols.py`
- Modify (tests): `backend/tests/repositories/nuget/packages.py`
- Create (tests): `backend/tests/repositories/nuget/test_symbols.py`

**Interfaces:**
- Consumes: `packages.InvalidPackage`, `packages.entries`, `packages.Entry`, `packages.Read`.
- Produces: `symbols.PREFIX = "symbols/"`, `PDBS_MOST = 1000`, `PDB_MOST = 256 MiB`; `symbols.Pdb(name, guid, checksum)` with `.path`; `symbols.read(name, data) -> Pdb` (raises `InvalidPackage`); `symbols.is_path(path) -> bool`; `symbols.asked(header) -> set[str] | None`; `symbols.entries(read, size) -> list[Entry]`. In the tests, `packages.GUID`, `packages.portable_pdb(guid=GUID, stamp=1, body=…)`, and `snupkg(..., pdbs=None)`, which now holds a portable PDB.

- [ ] **Step 1: Write the failing tests**

`packages.py` writes a portable PDB as far as a symbol server reads it: its metadata root and a `#Pdb` stream.

Change `backend/tests/repositories/nuget/packages.py`:

```diff
@@ -1,6 +1,8 @@
 """NuGet packages made in memory, as `dotnet pack` lays them out, for the tests."""
 
 import io
+import struct
+import uuid
 import zipfile
 from xml.sax.saxutils import escape
 
@@ -66,10 +68,38 @@ def nupkg(
     return written.getvalue()
 
 
-def snupkg(package_id: str = "MegooArti.Hello", version: str = "1.0.0") -> bytes:
-    """A symbol package of a package: its `.nuspec` says `SymbolsPackage`."""
+# A portable PDB's id, as the tests give it: its GUID, then a stamp.
+GUID = uuid.UUID("201d67af-c77a-4cd5-a666-8a65b7b7382d")
+
+
+def portable_pdb(guid: uuid.UUID = GUID, stamp: int = 1, body: bytes = b"debug info") -> bytes:
+    """A portable PDB as a compiler writes one, as far as a symbol server reads it: its
+    metadata root (`BSJB`), and a `#Pdb` stream that begins with its id."""
+    version = b"PDB v1.0\0\0\0\0"  # padded to four bytes
+    header_end = 16 + len(version) + 4 + 16
+    stream = guid.bytes_le + struct.pack("<I", stamp) + body
+    return (
+        b"BSJB"
+        + struct.pack("<HHII", 1, 1, 0, len(version))
+        + version
+        + struct.pack("<HH", 0, 1)
+        + struct.pack("<II", header_end, len(stream))
+        + b"#Pdb\0\0\0\0"
+        + stream
+    )
+
+
+def snupkg(
+    package_id: str = "MegooArti.Hello",
+    version: str = "1.0.0",
+    *,
+    pdbs: dict[str, bytes] | None = None,
+) -> bytes:
+    """A symbol package of a package: its `.nuspec` says `SymbolsPackage`, and it has
+    `lib/net8.0/Hello.pdb`, a portable PDB, unless it is given others."""
     spec = nuspec(package_id, version, package_types='<packageType name="SymbolsPackage"/>')
-    return nupkg(package_id, version, spec=spec, files={"lib/net8.0/Hello.pdb": b"BSJB"})
+    files = pdbs if pdbs is not None else {"lib/net8.0/Hello.pdb": portable_pdb()}
+    return nupkg(package_id, version, spec=spec, files=files)
 
 
 def reader(data: bytes):
```

Create `backend/tests/repositories/nuget/test_symbols.py`:

```python
"""What a symbol server keeps of a portable PDB: its key, as dotnet-symbol asks for it,
and its checksum, as it names it."""

import hashlib
import uuid

import pytest

from megooarti.repositories.nuget import symbols
from megooarti.repositories.nuget.packages import InvalidPackage
from tests.repositories.nuget.packages import GUID, portable_pdb


def test_a_portable_pdb_is_kept_at_its_key_with_its_checksum():
    data = portable_pdb(stamp=7)

    pdb = symbols.read("lib/net8.0/Hello.pdb", data)

    # As dotnet-symbol asks for Serilog's: the GUID as 32 hex digits, then FFFFFFFF.
    assert pdb.path == "symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.pdb"
    at = data.index(GUID.bytes_le)
    zeroed = data[:at] + b"\0" * 20 + data[at + 20 :]
    assert pdb.checksum == hashlib.sha256(zeroed).hexdigest()
    # The stamp is part of what is zeroed, not of the key.
    assert symbols.read("Hello.pdb", portable_pdb(stamp=8)).path == pdb.path


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0", "is a Windows PDB"),
        (b"MZ\x90\0", "is not a portable PDB"),
        (b"BSJB\x01\0", "metadata that cannot be read"),
        (portable_pdb().replace(b"#Pdb", b"#Str"), "has no PDB id"),
    ],
    ids=["windows", "other", "cut-short", "no-id"],
)
def test_what_is_not_a_portable_pdb_is_refused_by_name(data, said):
    with pytest.raises(InvalidPackage, match=said):
        symbols.read("Hello.pdb", data)


@pytest.mark.parametrize(
    ("path", "served"),
    [
        ("symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.pdb", True),
        ("symbols/Hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/Hello.pdb", False),
        ("symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382d00000001/hello.pdb", False),
        ("symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/other.pdb", False),
        ("symbols/hello.dll/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.dll", False),
    ],
    ids=["key", "capitals", "windows-key", "names", "not-a-pdb"],
)
def test_a_symbol_path_is_a_portable_pdbs_key(path, served):
    assert symbols.is_path(path) is served


def test_the_checksums_a_debugger_names_are_read():
    checksum = "AF671D20" + "0" * 56

    assert symbols.asked(None) is None
    assert symbols.asked(f"SHA256:{checksum}") == {checksum.lower()}
    assert symbols.asked(f"SHA1:{'0' * 40};SHA256:{checksum}") == {checksum.lower()}
    assert symbols.asked("nonsense") == set()


def test_another_guid_is_another_key():
    other = uuid.UUID("00000000-0000-0000-0000-000000000001")

    assert (
        "00000000000000000000000000000001FFFFFFFF"
        in symbols.read("Hello.pdb", portable_pdb(guid=other)).path
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/nuget/test_symbols.py -q`
Expected: an ImportError: `symbols` is not a module of `megooarti.repositories.nuget` yet.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/repositories/nuget/symbols.py`:

```python
"""What a symbol server (SSQP) keeps of a portable PDB: its key, and its checksum.

Pure functions. A portable PDB is ECMA-335 metadata: it begins with `BSJB`, and its
`#Pdb` stream begins with its id, a GUID and a stamp. A debugger asks for it at
`<name>/<GUID>FFFFFFFF/<name>`, the name in lower case and the GUID as 32 hex digits,
and says which it wants by its checksum (`SymbolChecksum: SHA256:<hex>`): the SHA-256
of the file with its id's 20 bytes set to 0, as the module's debug directory has it.
"""

import hashlib
import re
import struct
import uuid
from dataclasses import dataclass

from megooarti.repositories.nuget import packages
from megooarti.repositories.nuget.packages import InvalidPackage

PREFIX = "symbols/"
# What is read of a symbol package (section 9 of the spec).
PDBS_MOST = 1000
PDB_MOST = 256 * 1024 * 1024
_PORTABLE = b"BSJB"
_WINDOWS = b"Microsoft C/C++ MSF 7.00"
_ID_SIZE = 20
_NAME = re.compile(r"[a-z0-9_.+-]+\.pdb")
_KEY = re.compile(r"[0-9a-f]{32}FFFFFFFF")
# What a client may name in `SymbolChecksum`: SHA-256 alone, as a portable PDB's is.
_CHECKSUM = re.compile(r"SHA256:([0-9A-Fa-f]{64})")


@dataclass(frozen=True)
class Pdb:
    """A portable PDB, as a symbol server keeps it."""

    name: str  # its file's name, in lower case
    guid: str  # 32 hex digits, in lower case
    checksum: str  # SHA-256, 64 hex digits in lower case

    @property
    def path(self) -> str:
        return f"{PREFIX}{self.name}/{self.guid}FFFFFFFF/{self.name}"


def _streams(data: bytes) -> dict[str, tuple[int, int]]:
    """The metadata's streams, by name: where each is, and how long."""
    try:
        (length,) = struct.unpack_from("<I", data, 12)
        at = 16 + ((length + 3) & ~3)
        _, count = struct.unpack_from("<HH", data, at)
        at += 4
        found = {}
        for _ in range(count):
            offset, size = struct.unpack_from("<II", data, at)
            end = data.index(b"\0", at + 8)
            name = data[at + 8 : end].decode("ascii")
            found[name] = (offset, size)
            at = at + 8 + ((end - (at + 8) + 4) & ~3)
        return found
    except (struct.error, ValueError, UnicodeDecodeError):
        raise InvalidPackage("a .pdb in it has metadata that cannot be read") from None


def read(name: str, data: bytes) -> Pdb:
    """A portable PDB, by its file's name. Raises InvalidPackage for a Windows PDB, or
    for a file that is no PDB."""
    lower = name.rsplit("/", 1)[-1].lower()
    if data.startswith(_WINDOWS):
        raise InvalidPackage(f"{lower} is a Windows PDB: a symbol package has portable PDBs")
    if not data.startswith(_PORTABLE):
        raise InvalidPackage(f"{lower} is not a portable PDB")
    if not _NAME.fullmatch(lower):
        raise InvalidPackage(f"{lower} is not a name a symbol server can serve")
    stream = _streams(data).get("#Pdb")
    if stream is None or stream[1] < _ID_SIZE or stream[0] + _ID_SIZE > len(data):
        raise InvalidPackage(f"{lower} has no PDB id")
    start = stream[0]
    pdb_id = data[start : start + _ID_SIZE]
    guid = uuid.UUID(bytes_le=pdb_id[:16]).hex
    zeroed = data[:start] + b"\0" * _ID_SIZE + data[start + _ID_SIZE :]
    return Pdb(lower, guid, hashlib.sha256(zeroed).hexdigest())


def is_path(path: str) -> bool:
    """Whether a path is one a symbol server serves a portable PDB at."""
    parts = path.split("/")
    return (
        len(parts) == 4
        and parts[0] == PREFIX.rstrip("/")
        and parts[1] == parts[3]
        and _NAME.fullmatch(parts[1]) is not None
        and _KEY.fullmatch(parts[2]) is not None
    )


def asked(header: str | None) -> set[str] | None:
    """The checksums a client's `SymbolChecksum` names, in lower case; None if it sent
    none, which asks for the file whatever its checksum."""
    if header is None:
        return None
    return {found.lower() for found in _CHECKSUM.findall(header)}


async def entries(read: packages.Read, size: int) -> list[packages.Entry]:
    """The PDBs of a symbol package: the files of its zip named `.pdb`."""
    found = [
        entry for entry in await packages.entries(read, size) if entry.name.lower().endswith(".pdb")
    ]
    if len(found) > PDBS_MOST:
        raise InvalidPackage(f"it has more than {PDBS_MOST} PDBs")
    return found
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/nuget/test_symbols.py tests/repositories/nuget -q`
Expected: 259 passed: the PDB reader's own tests, and every NuGet test, with the test symbol package holding a portable PDB.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/nuget/symbols.py backend/tests/repositories/nuget
git commit -m "feat: a portable PDB's key and checksum, as a symbol server keeps it"
```

---

### Task 2: An API token with no user name

**Files:**
- Modify: `backend/src/megooarti/security/authentication.py`; `docs/administration.md`, `docs/api.md`
- Modify (tests): `backend/tests/security/test_authentication.py`

**Interfaces:**
- Consumes: `authenticate_secret`, `users.TOKEN_USERNAME`.
- Produces: HTTP Basic with no user name and an API token is the token's owner, as with `__token__`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/security/test_authentication.py`:

```diff
@@ -298,7 +298,8 @@ async def test_basic_with_the_token_user_name_is_the_tokens_owner(client, make_u
     await make_user("dana", roles=["admin"])
     token = await make_token(root)
 
-    for name in ("__token__", "__TOKEN__", " __token__ "):
+    # No name at all is as `__token__`, as dotnet-symbol sends a token.
+    for name in ("__token__", "__TOKEN__", " __token__ ", ""):
         response = await client.get(READ, headers=basic(name, token))
         assert response.json() == {"user": "root", "method": "token"}
 
@@ -308,11 +309,12 @@ async def test_the_token_user_name_takes_nothing_but_a_token(client, make_user,
     token = await make_token(root)
 
     with_password = await client.get(READ, headers=basic("__token__", PASSWORD))
+    nameless = await client.get(READ, headers=basic("", PASSWORD))
     with_unknown = await client.get(READ, headers=basic("__token__", "mga_" + "x" * 43))
     await disable_user(db, "root")
     with_a_disabled_owner = await client.get(READ, headers=basic("__token__", token))
 
-    for response in (with_password, with_unknown, with_a_disabled_owner):
+    for response in (with_password, nameless, with_unknown, with_a_disabled_owner):
         assert (response.status_code, error_code(response)) == (401, "unauthorized")
 
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/security/test_authentication.py -q`
Expected: 1 failed, 33 passed: HTTP Basic with no user name and a token is refused `401`.

- [ ] **Step 3: Write the code and the docs**

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -221,9 +221,11 @@ async def authenticate_secret(
     credentials are checked here, and so is anything else that takes a name and a
     secret, so that the limits on failed attempts are the same everywhere.
 
-    The name `__token__` is nobody's: with it, the token alone says who is asking.
+    The name `__token__` is nobody's, and nor is no name at all: with either, the token
+    alone says who is asking.
     """
-    if users.normalise_username(username) == users.TOKEN_USERNAME:
+    # No name says the same, as dotnet-symbol and Azure DevOps's clients send a token.
+    if users.normalise_username(username) in ("", users.TOKEN_USERNAME):
         if secret.startswith(TOKEN_PREFIX):
             return await _authenticate_token(db, request, secret)
         # Not a token at all. A failed attempt, counted against the address.
```

Change `docs/administration.md`:

```diff
@@ -15,8 +15,8 @@ Users, roles, your own API tokens and anonymous access are managed in the web UI
   repository. Roles can contain other roles.
 - **Personal API tokens** (`mga_…`) are created under `/api/v1/me/tokens` while signed
   in with a password. Use one as a bearer token, or as the password in HTTP Basic,
-  with your user name or with the name `__token__`, which is how Python's tools send
-  a token. A token can be limited to a list of patterns and can expire.
+  with your user name, with the name `__token__`, which is how Python's tools send
+  a token, or with no name, which is how `dotnet-symbol` sends one. A token can be limited to a list of patterns and can expire.
 - **Anonymous access** is off by default. When turned on under `/api/v1/settings`,
   requests without credentials act as the built-in `anonymous` user. That user starts
   with the built-in `anonymous` role, which allows reading **every** repository. To
```

Change `docs/api.md`:

```diff
@@ -16,8 +16,8 @@ old one kept for a while.
 ## Who is calling
 
 - **HTTP Basic**, with a user name and a password, or with an API token in the place
-  of the password: `curl -u ci:mga_...`. The name `__token__` stands for whoever the
-  token belongs to.
+  of the password: `curl -u ci:mga_...`. The name `__token__`, or no name, stands for
+  whoever the token belongs to.
 - **A bearer token**: `Authorization: Bearer mga_...`.
 - **A session**, as the web UI has: `POST /api/v1/auth/login` with a user name and a
   password sets a cookie and answers with a `csrf_token`. A request that uses the
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/security tests/test_documents.py -q`
Expected: 411 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/security backend/tests/security docs/administration.md docs/api.md
git commit -m "feat: an API token with no user name is its owner's, as dotnet-symbol sends one"
```

---

### Task 3: The symbol server

**Files:**
- Create: `backend/src/megooarti/repositories/nuget/symbol_server.py`
- Modify: `backend/src/megooarti/repositories/remote.py`, `proxy.py`; `backend/src/megooarti/repositories/nuget/paths.py`, `grouped.py`, `format.py`
- Create (tests): `backend/tests/repositories/nuget/test_symbol_server.py`
- Modify (tests): `backend/tests/repositories/nuget/test_content.py`

**Interfaces:**
- Consumes: Task 1's `symbols.*` and test helpers; `proxy.ensure_cached`, `proxy.Source`; the context's `store`, `get`, `respond`, `files`, `delete`, `stage_bytes`, `discard`, `read_staged`.
- Produces:
  - `remote.download(..., headers=None)`; `proxy.Source.headers: Mapping[str, str]`, sent with a download.
  - `paths.classify` gives `symbol` for a portable PDB's key.
  - `symbol_server.CHECKSUM = "symbol_checksum"`; `symbol_server.staged_pdbs(context, read, size) -> list[(Pdb, StagedBlob)]`; `symbol_server.keep(context, nuspec, staged)`; `symbol_server.serve(context, request, path)`; `symbol_server.serve_proxy(context, request, path)`; `symbol_server.checksum_of(context, path, staged) -> dict`.
  - In `format.py`: a symbol package's PDBs kept as it is pushed or uploaded, a symbol package's deletion taking its PDBs, `symbol` paths served by a hosted repository and a proxy, a fetched PDB described by its checksum, and `format.symbols_of(address)`, the setup's `Symbols` snippet. `grouped.handle_group` asks the members for a PDB.

- [ ] **Step 1: Write the failing tests**

`test_symbol_server.py` pushes a package and its symbol package, and stands a symbol server in for nuget.org's. `test_content.py`'s component now lists its PDB, and the setup has a fifth snippet.

Create `backend/tests/repositories/nuget/test_symbol_server.py`:

```python
"""The symbol server of NuGet repositories (section 8): the portable PDBs of each symbol
package kept at their keys, served to a debugger that names their checksum; a proxy's
symbol server asked with the debugger's checksum; a group's members asked in order."""

import uuid

import pytest

from megooarti.repositories.nuget import symbols
from tests.accounts import error_code
from tests.repositories.nuget.conftest import URL, create, push
from tests.repositories.nuget.packages import nupkg, portable_pdb, snupkg

PDB = portable_pdb()
KEPT = symbols.read("Hello.pdb", PDB)
KEY = KEPT.path.removeprefix("symbols/")
CHECKSUM = {"SymbolChecksum": f"SHA256:{KEPT.checksum.upper()}"}
SERVER = "http://symbols.test/download/symbols"


@pytest.fixture
async def pushed(client, hosted, root):
    """MegooArti.Hello 1.0.0, and its symbol package with one portable PDB."""
    assert (await push(client, root, nupkg())).status_code == 201
    assert (await push(client, root, snupkg(), symbols=True)).status_code == 201


async def test_a_pdb_is_served_at_its_key_to_whoever_names_its_checksum(client, root, pushed):
    named = await client.get(f"{URL}/{KEPT.path}", headers={**root, **CHECKSUM})
    unnamed = await client.get(f"{URL}/{KEPT.path}", headers=root)
    other = {"SymbolChecksum": f"SHA256:{'0' * 64}"}
    wrong = await client.get(f"{URL}/{KEPT.path}", headers={**root, **other})

    assert named.content == PDB
    assert named.headers["content-type"] == "application/octet-stream"
    assert unnamed.content == PDB
    assert wrong.status_code == 404


async def test_a_pdb_is_a_file_of_its_version_and_goes_with_it(client, root, pushed):
    detail = await client.get("/api/v1/content/nuget-hosted/components", headers=root)
    deleted = await client.delete(f"{URL}/api/v2/package/MegooArti.Hello/1.0.0", headers=root)
    after = await client.get(f"{URL}/{KEPT.path}", headers=root)

    assert detail.json()["items"][0]["name"] == "MegooArti.Hello"
    assert deleted.status_code == 204
    assert after.status_code == 404


async def test_deleting_a_symbol_package_deletes_its_pdbs(client, root, pushed):
    folder = "v3/package/megooarti.hello/1.0.0"

    deleted = await client.delete(
        "/api/v1/content/nuget-hosted/asset",
        params={"path": f"{folder}/megooarti.hello.1.0.0.snupkg"},
        headers=root,
    )
    after = await client.get(f"{URL}/{KEPT.path}", headers=root)
    package = await client.get(f"{URL}/{folder}/megooarti.hello.1.0.0.nupkg", headers=root)

    assert deleted.status_code == 204, deleted.text
    assert after.status_code == 404
    assert package.status_code == 200


@pytest.mark.parametrize(
    ("pdb", "said"),
    [
        (b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0", "Windows PDB"),
        (b"not a pdb", "not a portable PDB"),
    ],
    ids=["windows", "other"],
)
async def test_a_symbol_package_of_what_is_not_a_portable_pdb_is_refused(
    client, hosted, root, pdb, said
):
    await push(client, root, nupkg())
    pdbs = {"lib/net8.0/Good.pdb": PDB, "lib/net8.0/Hello.pdb": pdb}

    answer = await push(client, root, snupkg(pdbs=pdbs), symbols=True)
    kept = await client.get(f"{URL}/{KEPT.path.replace('hello.pdb', 'good.pdb')}", headers=root)
    folder = "v3/package/megooarti.hello/1.0.0"
    package = await client.get(f"{URL}/{folder}/megooarti.hello.1.0.0.snupkg", headers=root)

    assert (answer.status_code, error_code(answer)) == (400, "invalid_package")
    assert said in answer.json()["error"]["message"]
    assert kept.status_code == 404
    assert package.status_code == 404


async def test_a_symbol_package_pushed_again_keeps_only_its_own_pdbs(client, db, root):
    await create(db, hosted={"deployment_policy": "allow_redeploy"})
    await push(client, root, nupkg())
    await push(client, root, snupkg(), symbols=True)
    rebuilt = portable_pdb(guid=uuid.UUID("00000000-0000-0000-0000-000000000002"))

    again = await push(client, root, snupkg(pdbs={"lib/net8.0/Hello.pdb": rebuilt}), symbols=True)
    old = await client.get(f"{URL}/{KEPT.path}", headers=root)
    new = await client.get(f"{URL}/{symbols.read('Hello.pdb', rebuilt).path}", headers=root)

    assert again.status_code == 200, again.text
    assert old.status_code == 404
    assert new.content == rebuilt


@pytest.fixture
async def proxied(client, root, fake_remote):
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-org",
            "format": "nuget",
            "type": "proxy",
            "format_config": {"symbol_url": SERVER},
            "proxy": {"remote_url": "http://remote.test/v3/index.json"},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text
    fake_remote.files[f"download/symbols/{KEY}"] = PDB
    return fake_remote


async def test_a_proxy_asks_its_symbol_server_with_the_checksum_and_keeps_the_pdb(
    client, root, proxied
):
    address = f"/repository/nuget-org/{KEPT.path}"
    first = await client.get(address, headers={**root, **CHECKSUM})
    second = await client.get(address, headers={**root, **CHECKSUM})
    other = {"SymbolChecksum": f"SHA256:{'0' * 64}"}
    wrong = await client.get(address, headers={**root, **other})

    assert first.content == second.content == PDB
    asked = [seen for seen in proxied.requests if seen["path"] == f"/download/symbols/{KEY}"]
    assert len(asked) == 1  # kept
    assert asked[0]["headers"]["symbolchecksum"] == CHECKSUM["SymbolChecksum"]
    assert wrong.status_code == 404  # what is kept is not what was asked for


async def test_a_proxy_without_a_symbol_server_has_no_symbols(client, root, fake_remote):
    await client.post(
        "/api/v1/repositories",
        json={
            "name": "plain",
            "format": "nuget",
            "type": "proxy",
            "proxy": {"remote_url": "http://remote.test/v3/index.json"},
        },
        headers=root,
    )

    answer = await client.get(f"/repository/plain/{KEPT.path}", headers=root)

    assert answer.status_code == 404
    assert fake_remote.requests == []


async def test_a_group_serves_its_members_pdbs_in_order(client, root, pushed, proxied):
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-all",
            "format": "nuget",
            "type": "group",
            "group": {"members": ["nuget-hosted", "nuget-org"]},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text

    answer = await client.get(f"/repository/nuget-all/{KEPT.path}", headers={**root, **CHECKSUM})

    assert answer.content == PDB
    assert proxied.requests == []  # the hosted member had it
```

Change `backend/tests/repositories/nuget/test_content.py`:

```diff
@@ -46,6 +46,7 @@ async def test_a_version_is_a_component_with_its_files_and_how_to_use_it(client,
 
     assert (component["name"], component["version"]) == ("MegooArti.Hello", "1.0.0-beta")
     assert sorted(file["path"].rpartition("/")[2] for file in detail["files"]) == [
+        "hello.pdb",
         "megooarti.hello.1.0.0-beta.nupkg",
         "megooarti.hello.1.0.0-beta.snupkg",
         "megooarti.hello.nuspec",
@@ -71,7 +72,7 @@ async def test_megooartis_own_search_finds_a_package_by_its_description(client,
 async def test_a_repository_says_how_dotnet_is_given_it_as_a_source(client, hosted, root):
     view = (await client.get(f"{CONTENT}/nuget-hosted", headers=root)).json()
 
-    dotnet, config, chocolatey, powershell = view["setup"]
+    dotnet, config, chocolatey, powershell, symbols = view["setup"]
     assert not dotnet["text"].startswith("#")
     assert dotnet["text"] == (
         'dotnet nuget add source "https://test/repository/nuget-hosted/index.json" '
@@ -98,6 +99,14 @@ async def test_a_repository_says_how_dotnet_is_given_it_as_a_source(client, host
         '-Uri "https://test/repository/nuget-hosted/index.json" -Trusted\n'
     )
     assert "-Credential $credential" in powershell["text"]
+    # A debugger is given the symbol server under the repository's address.
+    assert symbols["text"] == (
+        "# Visual Studio: Tools > Options > Debugging > Symbols, add "
+        "https://test/repository/nuget-hosted/symbols/\n"
+        'dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" '
+        "https://test/repository/nuget-hosted/symbols/ \\\n"
+        "  --symbols MyApp.dll"
+    )
 
 
 async def test_a_source_over_plain_http_is_allowed_so_and_a_name_is_made_an_element(
@@ -136,7 +145,7 @@ async def test_a_proxy_of_a_v2_feed_is_given_as_a_v2_source(client, root):
 
     view = (await client.get(f"{CONTENT}/gallery", headers=root)).json()
 
-    dotnet, config, chocolatey, powershell = (usage["text"] for usage in view["setup"])
+    dotnet, config, chocolatey, powershell, _ = (usage["text"] for usage in view["setup"])
     assert '"https://test/repository/gallery/" --name gallery' in dotnet
     assert 'value="https://test/repository/gallery/"' in config
     assert '--source="https://test/repository/gallery/"' in chocolatey
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/nuget -q`
Expected: 9 failed, 259 passed: no repository serves `symbols/` yet, so a PDB is `404` and a symbol package of a Windows PDB is taken; a component lists no PDB, and the setup has four snippets.

- [ ] **Step 3: Write the code**

The proxy engine sends a source's own headers with a download: a symbol server is told what is wanted by `SymbolChecksum`.

Change `backend/src/megooarti/repositories/remote.py`:

```diff
@@ -491,9 +491,14 @@ async def download(
     last_modified: str | None = None,
     accept: str | None = None,
     sign_in: SignIn | None = None,
+    headers: Mapping[str, str] | None = None,
 ) -> Fetched | NotModified | Missing | Failed:
-    """Fetch a file completely, or learn that it is unchanged, absent or unavailable."""
-    headers = _request_headers(accept, etag, last_modified)
+    """Fetch a file completely, or learn that it is unchanged, absent or unavailable.
+
+    `headers` are sent besides those every fetch sends, for a remote that is told what
+    is wanted by a header of its own (a symbol server, by `SymbolChecksum`).
+    """
+    headers = {**(headers or {}), **_request_headers(accept, etag, last_modified)}
     try:
         response = await _open(
             client, "GET", url, authorization=authorization, headers=headers, sign_in=sign_in
```

Change `backend/src/megooarti/repositories/proxy.py`:

```diff
@@ -58,6 +58,9 @@ class Source:
     # its that is asked apart from its files, such as a search on another host: its
     # failing must not stop the files being fetched. The failure is recorded all the same.
     blocks: bool = True
+    # Headers to send with a download besides those every fetch sends, for a remote that
+    # is told what is wanted by one of its own: a symbol server, by `SymbolChecksum`.
+    headers: Mapping[str, str] = field(default_factory=dict)
 
 
 @dataclass(frozen=True)
@@ -326,6 +329,7 @@ async def _refresh(
         last_modified=known.get("remote_last_modified"),
         accept=None if source is None else source.accept,
         sign_in=_sign_in(context, source),
+        headers=None if source is None else source.headers,
     )
     now = utcnow()
 
```

Create `backend/src/megooarti/repositories/nuget/symbol_server.py`:

```python
"""The symbol server of a NuGet repository (section 8 of the spec).

A hosted repository keeps each portable PDB of a symbol package it is given at the
PDB's key, as a file of the package's version, with the PDB's checksum; it serves it to
a debugger that asks for it by that key, and names no other checksum. A proxy with a
symbol server (`format_config.symbol_url`) asks that server for what it does not keep,
with the debugger's checksum, and keeps what it is given. A group asks its members in
order, as the group engine does for any file.
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import packages, records, symbols
from megooarti.repositories.nuget.packages import Nuspec
from megooarti.repositories.proxy import Source
from megooarti.storage.backends import StagedBlob

# Where a file's attributes keep a PDB's checksum.
CHECKSUM = "symbol_checksum"
_PDB = "application/octet-stream"
_HEADER = "SymbolChecksum"


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "This repository has no such symbol file.")


async def staged_pdbs(
    context: RepositoryContext, read: packages.Read, size: int
) -> list[tuple[symbols.Pdb, StagedBlob]]:
    """Each portable PDB of a symbol package, read and staged one at a time. Raises
    InvalidPackage, with nothing left staged, for one that is not a portable PDB."""
    found = await symbols.entries(read, size)
    staged: list[tuple[symbols.Pdb, StagedBlob]] = []
    try:
        for entry in found:
            data = await packages.extract(read, entry, symbols.PDB_MOST)
            pdb = symbols.read(entry.name, data)
            if all(pdb.path != kept.path for kept, _ in staged):
                staged.append((pdb, await context.stage_bytes(data)))
    except BaseException:
        for _, blob in staged:
            await context.discard(blob)
        raise
    return staged


async def keep(
    context: RepositoryContext, nuspec: Nuspec, staged: list[tuple[symbols.Pdb, StagedBlob]]
) -> None:
    """A version's PDBs, each at its key, in place of those it had."""
    said = nuspec.as_json()
    paths = {pdb.path for pdb, _ in staged}
    for held in await context.files("", nuspec.id, nuspec.version.lower()):
        if symbols.is_path(held.path) and held.path not in paths:
            await context.delete(held.path)
    for pdb, blob in staged:
        await context.store(
            pdb.path,
            blob,
            content_type=_PDB,
            attributes={records.DECLARED: said, CHECKSUM: pdb.checksum},
        )


async def _respond(context: RepositoryContext, request: Request, path: str) -> Response:
    """A PDB this repository keeps, if the checksums the debugger names include its own."""
    asset = await context.get(path)
    if asset is None:
        raise _not_found()
    wanted = symbols.asked(request.headers.get(_HEADER))
    if wanted is not None and (asset.attributes or {}).get(CHECKSUM) not in wanted:
        raise _not_found()
    return await context.respond(path, request)


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    """`symbols/<name>/<key>/<name>` of a hosted repository."""
    return await _respond(context, request, path)


async def serve_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """`symbols/<name>/<key>/<name>` of a proxy: asked of its symbol server, with the
    debugger's checksum, and kept. A proxy without a symbol server has none."""
    server = context.repository.config.get("format_config", {}).get("symbol_url")
    if not server:
        raise _not_found()
    header = request.headers.get(_HEADER)
    source = Source(
        f"{server}/{path.removeprefix(symbols.PREFIX)}",
        headers={_HEADER: header} if header else {},
        # A server that has no file for one checksum may have it for another.
        remember_missing=False,
    )
    await proxy.ensure_cached(context, path, source=source)
    return await _respond(context, request, path)


async def checksum_of(context: RepositoryContext, path: str, staged: StagedBlob) -> dict:
    """What a proxy keeps of a PDB it fetched: its checksum, if it is a portable PDB."""
    data = await context.read_staged(staged, limit=symbols.PDB_MOST)
    if data is None:
        return {}
    try:
        return {CHECKSUM: symbols.read(path.rsplit("/", 1)[-1], data).checksum}
    except packages.InvalidPackage:
        return {}
```

Change `backend/src/megooarti/repositories/nuget/paths.py`:

```diff
@@ -6,7 +6,7 @@ version in a path is normalized.
 
 from dataclasses import dataclass
 
-from megooarti.repositories.nuget import odata, versions
+from megooarti.repositories.nuget import odata, symbols, versions
 
 SERVICE_INDEX = "index.json"
 PACKAGES = "v3/package/"
@@ -24,7 +24,7 @@ SYMBOL_PUBLISH = "api/v2/symbolpackage"
 class NuGetPath:
     # service-index, versions, package, nuspec, symbols, registration, leaf, search,
     # autocomplete, publish, symbol-publish, delete, page, v2 (V2's feed), download (V2's
-    # address of a package), other
+    # address of a package), symbol (a portable PDB at its key), other
     kind: str
     id: str = ""  # lower case
     version: str = ""  # normalized, lower case
@@ -65,6 +65,8 @@ def classify(path: str) -> NuGetPath:
         return NuGetPath("service-index")
     if odata.is_v2(path):
         return NuGetPath("v2")
+    if symbols.is_path(path):
+        return NuGetPath("symbol")
     parts = path.split("/")
     if len(parts) == 3 and parts[0] == "package":
         version = _version(parts[2])
```

Change `backend/src/megooarti/repositories/nuget/grouped.py`:

```diff
@@ -91,10 +91,10 @@ async def handle_group(
         if audit is None:
             raise _not_found()
         return await responses.respond_json(context, request, audit)
-    # A package, its `.nuspec`, a file of NuGet Audit's, a package at V2's address: the
-    # first member that has it. Nothing else is asked of the members: what they would
-    # answer has their addresses.
-    if parsed.kind == "download" or path.startswith(paths.PACKAGES):
+    # A package, its `.nuspec`, a file of NuGet Audit's, a package at V2's address, a
+    # PDB at its key: the first member that has it. Nothing else is asked of the members:
+    # what they would answer has their addresses.
+    if parsed.kind in ("download", "symbol") or path.startswith(paths.PACKAGES):
         return await group.handle_group(context, request, path, serve)
     if proxied.vulnerability_name(path) is not None:
         return await group.handle_group(context, request, path, serve)
```

Change `backend/src/megooarti/repositories/nuget/format.py`:

```diff
@@ -51,6 +51,7 @@ from megooarti.repositories.nuget import (
     queries,
     records,
     responses,
+    symbol_server,
     v2,
     versions,
 )
@@ -164,19 +165,31 @@ async def _keep_package(
 async def _keep_symbols(
     context: RepositoryContext, staged: StagedBlob, package: packages.Package
 ) -> bool:
-    """A symbol package, beside the package it is of: that must be here."""
+    """A symbol package, beside the package it is of: that must be here. Each of its
+    portable PDBs is kept at its key, as a file of the version (section 8)."""
     nuspec = await _spelled(context, package.nuspec)
     if await context.stat(paths.package_path(nuspec.id, nuspec.version)) is None:
         await context.discard(staged)
         raise _not_found(
             f"This repository has no {nuspec.id} {nuspec.version}: push the package first."
         )
-    _, created = await context.store(
-        paths.symbols_path(nuspec.id, nuspec.version),
-        staged,
-        content_type=_PACKAGE,
-        attributes={records.DECLARED: nuspec.as_json()},
-    )
+    try:
+        pdbs = await symbol_server.staged_pdbs(context, _ranges(context, staged), staged.size)
+    except packages.InvalidPackage as error:
+        await context.discard(staged)
+        raise _invalid(error) from None
+    try:
+        _, created = await context.store(
+            paths.symbols_path(nuspec.id, nuspec.version),
+            staged,
+            content_type=_PACKAGE,
+            attributes={records.DECLARED: nuspec.as_json()},
+        )
+        await symbol_server.keep(context, nuspec, pdbs)
+    except BaseException:
+        for _, blob in pdbs:
+            await context.discard(blob)
+        raise
     return created
 
 
@@ -332,6 +345,8 @@ async def _read_request(
         return await v2.answer(context, request, path)
     if parsed.kind == "download":
         return await v2.download(context, request, parsed)
+    if parsed.kind == "symbol":
+        return await symbol_server.serve(context, request, path)
     raise _not_found()
 
 
@@ -395,9 +410,20 @@ def setup_of(address: str, name: str, *, v3: bool = True) -> list[Usage]:
         Usage("nuget.config", "xml", config),
         Usage("Chocolatey", "shell", chocolatey),
         Usage("PowerShell", "powershell", powershell),
+        Usage("Symbols", "shell", symbols_of(address)),
     ]
 
 
+def symbols_of(address: str) -> str:
+    """The repository as a symbol server: of Visual Studio, and of `dotnet-symbol`."""
+    server = f"{address}symbols/"
+    return (
+        f"# Visual Studio: Tools > Options > Debugging > Symbols, add {server}\n"
+        f'dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" {server} \\\n'
+        "  --symbols MyApp.dll"
+    )
+
+
 # The protocols a proxy may speak to its remote, and serve: chosen once (D2).
 PROTOCOLS = ("v3", "v2")
 
@@ -442,6 +468,8 @@ async def describe_fetched(
     `.nuspec` says. Nothing for what cannot be read: it is the remote's."""
     kind = paths.classify(path).kind
     try:
+        if kind == "symbol":
+            return await symbol_server.checksum_of(context, path, staged)
         if kind == "package":
             nuspec = (await packages.read(_ranges(context, staged), staged.size)).nuspec
         elif kind == "nuspec":
@@ -488,6 +516,8 @@ class NuGetFormat(Format):
         self, context: RepositoryContext, request: Request, path: str
     ) -> Response:
         path = paths.v2_path(path)
+        if paths.classify(path).kind == "symbol":
+            return await symbol_server.serve_proxy(context, request, path)
         if context.repository.config.get("format_config", {}).get("protocol") == "v2":
             return await proxied_v2.handle_proxy(context, request, path)
         return await proxied.handle_proxy(context, request, path)
@@ -545,10 +575,17 @@ class NuGetFormat(Format):
         return stored
 
     async def delete_asset(self, context: RepositoryContext, path: str) -> bool:
-        """A package goes with its version's every file; its `.nuspec` goes with it."""
+        """A package goes with its version's every file; its `.nuspec` goes with it, and
+        a symbol package's PDBs with it."""
         parsed = paths.classify(path)
         if parsed.kind == "package":
             return await _delete_version(context, parsed.id, parsed.version)
+        if parsed.kind == "symbols":
+            spelling = await context.spelling("", parsed.id)
+            held = [] if spelling is None else await context.files("", spelling, parsed.version)
+            for one in held:
+                if paths.classify(one.path).kind == "symbol":
+                    await context.delete(one.path)
         if parsed.kind == "nuspec":
             package = paths.package_path(parsed.id, parsed.version)
             if await context.stat(path) is not None and await context.stat(package) is not None:
@@ -587,7 +624,7 @@ class NuGetFormat(Format):
 
     def content_type(self, path: str, declared: str | None) -> str | None:
         kind = paths.classify(path).kind
-        if kind in ("package", "symbols"):
+        if kind in ("package", "symbols", "symbol"):
             return _PACKAGE
         if kind == "nuspec":
             return _NUSPEC
```

- [ ] **Step 4: Run the tests to verify they pass**

The engine's own tests are run as well, unchanged.

Run (in `backend/`): `uv run pytest tests/repositories/nuget tests/repositories/test_proxy.py tests/repositories/test_remote.py tests/repositories/test_proxy_documents.py -q`
Expected: 411 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "feat: NuGet's symbol server, of hosted repositories, proxies and groups"
```

---

### Task 4: dotnet-symbol against the built image, and the guide

**Files:**
- Modify (tests): `backend/tests/test_nuget_client.py`
- Modify: `docs/formats/nuget.md`

**Interfaces:**
- Consumes: Tasks 2 and 3 through the built image; the dotnet test's `dotnet`, `config`, `work`, `grouped`, `token`, `package_id`, `VERSION`, `HOSTED`, `PROXY`, `GROUP`.
- Produces: in the dotnet test, `DOTNET_SYMBOL`, `SYMBOLS`, `symbols_of(sdk, work, token, repository)`, and `tools.config` in each SDK's folder (the proxy of nuget.org, to install tools through).

- [ ] **Step 1: Write the tests**

`dotnet-symbol`, installed through the proxy of nuget.org, fetches the PDB of each SDK's package for its DLL, signed in with the API token alone: from the hosted repository before the version is deleted, and through the group after it is pushed again.

Change `backend/tests/test_nuget_client.py`:

```diff
@@ -7,6 +7,7 @@ reaches nuget.org only through the proxy.
 """
 
 import subprocess
+import zipfile
 from pathlib import Path
 
 import pytest
@@ -88,6 +89,21 @@ CODE
 dotnet run
 """
 
+# dotnet-symbol, installed through the proxy of nuget.org, fetches the PDB of the SDK's
+# package, `$1`, for its DLL, from the symbol server of the repository `$3`, signed in
+# with the API token `$2`, as it signs in: with no user name.
+DOTNET_SYMBOL = "10.0.750501"
+SYMBOLS = f"""
+set -e
+cd /work
+dotnet tool install --global dotnet-symbol --version {DOTNET_SYMBOL} \\
+  --configfile tools.config > /dev/null
+export PATH="$PATH:/root/.dotnet/tools"
+dotnet-symbol --authenticated-server-path "$2" "http://gateway/repository/$3/symbols/" \\
+  --symbols --output "symbols-$3" lib/bin/Release/*/"$1.dll"
+ls "symbols-$3"
+"""
+
 # Builds `/work/out/<id>.1.0.0.nupkg` and its `.snupkg`: a library that says hello.
 PACK = f"""
 set -e
@@ -149,6 +165,8 @@ def work(token, tmp_path_factory) -> dict[str, Path]:
     for sdk in IMAGES:
         folder = tmp_path_factory.mktemp(f"dotnet{sdk}")
         (folder / "nuget.config").write_text(config(HOSTED), encoding="utf-8", newline="\n")
+        tools = config(PROXY, "nuget-org")
+        (folder / "tools.config").write_text(tools, encoding="utf-8", newline="\n")
         packed = dotnet(sdk, folder, PACK, package_id(sdk))
         assert packed.returncode == 0, said(packed)
         folders[sdk] = folder
@@ -207,6 +225,14 @@ def test_dotnet_finds_the_package_and_restores_it_into_a_project(work, sdk):
     assert restored.stdout.splitlines()[-1] == f"hello from {package_id(sdk)}"
 
 
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+def test_dotnet_symbol_fetches_the_packages_pdb(work, token, sdk):
+    fetched, kept, pushed = symbols_of(sdk, work[sdk], token, HOSTED)
+
+    assert fetched.returncode == 0, said(fetched)
+    assert kept == pushed
+
+
 @pytest.mark.parametrize("sdk", sorted(IMAGES))
 def test_dotnet_deletes_a_version(work, token, sdk):
     deleted = dotnet(
@@ -222,6 +248,16 @@ def test_dotnet_deletes_a_version(work, token, sdk):
     assert fetch(f"v3/package/{lower(sdk)}/index.json") == 404
 
 
+def symbols_of(sdk: str, work: Path, token: str, repository: str):
+    """The PDB dotnet-symbol fetched of the SDK's package, and the one its symbol package has."""
+    fetched = dotnet(sdk, work, SYMBOLS, package_id(sdk), token, repository)
+    with zipfile.ZipFile(work / "out" / f"{package_id(sdk)}.{VERSION}.snupkg") as packed:
+        (name,) = [entry for entry in packed.namelist() if entry.endswith(".pdb")]
+        pushed = packed.read(name)
+    kept = work / f"symbols-{repository}" / f"{package_id(sdk)}.pdb"
+    return fetched, kept.read_bytes() if kept.exists() else None, pushed
+
+
 @pytest.fixture(scope="module")
 def through(token, tmp_path_factory) -> dict[str, Path]:
     """Each SDK's own folder whose one source is the proxy of nuget.org."""
@@ -327,3 +363,11 @@ def test_nuget_audit_warns_of_a_vulnerable_package_with_the_data_passed_on(reque
     assert warned, said(restored)
     assert "Newtonsoft.Json" in warned[0]
     assert "NU1905" not in restored.stdout  # the source had the data
+
+
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+def test_dotnet_symbol_fetches_the_packages_pdb_through_a_group(grouped, work, token, sdk):
+    fetched, kept, pushed = symbols_of(sdk, work[sdk], token, GROUP)
+
+    assert fetched.returncode == 0, said(fetched)
+    assert kept == pushed
```

- [ ] **Step 2: Write the guide**

Change `docs/formats/nuget.md`:

````diff
@@ -146,6 +146,21 @@ curl -u admin -H 'Content-Type: application/json' -d '{
 - **Symbol packages** (`.snupkg`, made by `dotnet pack` with `--include-symbols
   -p:SymbolPackageFormat=snupkg`) are pushed with their package by `dotnet nuget push`,
   and kept beside it. One pushed before its package is refused with `404`.
+- **A symbol server.** Each portable PDB of a symbol package is kept at the key a
+  debugger asks for it by, under `symbols/`; a symbol package with a Windows PDB, or a
+  `.pdb` that is no PDB, is refused with `400 invalid_package`. A debugger that names
+  the checksum it wants (`SymbolChecksum`) is given the PDB only if it is that one. In
+  Visual Studio, add the repository's address, then `symbols/`, under Tools > Options >
+  Debugging > Symbols; with `dotnet-symbol`, sign in with an API token:
+
+  ```bash
+  dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" \
+    https://repo.example.com/repository/nuget-hosted/symbols/ --symbols MyApp.dll
+  ```
+
+  A proxy with `format_config.symbol_url` (`https://symbols.nuget.org/download/symbols`
+  for nuget.org's packages) asks that server for what it does not keep, and keeps what
+  it is given; a group asks its members in order.
 - **Deleting** a version (`dotnet nuget delete <id> <version>`, which needs the
   `delete` permission, or the web UI) removes it and its every file: its package, its
   `.nuspec` and its symbol package. A package's `.nuspec` cannot be deleted on its own.
@@ -166,8 +181,7 @@ curl -u admin -H 'Content-Type: application/json' -d '{
   checked again with the remote after `metadata_max_age_minutes`; what the proxy passes
   on of them has the feed's addresses made its own. A search is passed on to the feed
   every time, and not kept. A proxy's `format_config.protocol` is `v3`, the default;
-  `format_config.symbol_url` names a symbol server to proxy, which a later version
-  serves. A search that fails is said to have failed, and does not stop the proxy
+  `format_config.symbol_url` names a symbol server to proxy (see above). A search that fails is said to have failed, and does not stop the proxy
   fetching packages.
 - **V2's feed** answers the queries that `nuget.exe`, `choco` and PSResourceGet send:
   `FindPackagesById()`, `Packages(Id='…',Version='…')`, `Packages()` and `Search()`,
@@ -224,8 +238,9 @@ a proxy of nuget.org, a package restored into a project that runs, found with
 `dotnet package search`, and its newer versions listed by `dotnet list package
 --outdated`; through a group of the two, a project that restores a pushed package and
 one of nuget.org's and runs, both found with `dotnet package search`, and newer versions
-listed; and through the proxy and through the group, NuGet Audit's warning of a package
-with a known vulnerability.
+listed; through the proxy and through the group, NuGet Audit's warning of a package
+with a known vulnerability; and with `dotnet-symbol` 10.0, the PDB of a pushed package
+fetched for its DLL from the hosted repository and through the group.
 
 Tested with `nuget.exe` 6.14 under Mono 6.12, over V2 and over V3: a package built
 with `nuget pack`, pushed, installed at a version and at its newest, listed (over V2),
````

- [ ] **Step 3: Run the tests**

Run (in `backend/`): `uv run pytest tests/test_documents.py -q`
Expected: 140 passed.

Run (in `backend/`): `uv run pytest -m docker tests/test_nuget_client.py -q`
Expected: 24 passed: the twenty of plans 13a to 13c, and `dotnet-symbol`'s four (each SDK, from the hosted repository and through the group).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_nuget_client.py docs/formats/nuget.md
git commit -m "test: dotnet-symbol fetches a package's PDB from a hosted repository and through a group; docs: the symbol server"
```

---

### Task 5: The spec, and every suite

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-nuget-design.md`

- [ ] **Step 1: Write what this plan settled into the spec, and mend section 8's key**

Change `docs/superpowers/specs/2026-10-15-nuget-design.md`:

```diff
@@ -194,6 +194,19 @@ A package client signs in with an API token: as the `X-NuGet-ApiKey` header (wha
 | G7 | A V2 query that asks for the newest version (`IsLatestVersion`, `IsAbsoluteLatestVersion`) is answered by a group with each id's newest of its members' newest, once, where the id's first entry was; the others are dropped and counted so. | Each member's newest is newest of what it has: a group of a hosted repository and a feed that both had an id listed it twice, and `choco install` without a version could take the older. |
 | G8 | A query for which a member's feed still has a next page after the ten a group follows (G2), with fewer entries read than the group asks for, is refused with `400 unsupported_query`, which says to narrow it. | Past the tenth page, the feed seemed to end, its count saying otherwise. |
 
+### Settled while building plan 13f
+
+| # | What | Why |
+| --- | --- | --- |
+| S1 | A portable PDB is kept and served at `symbols/<name>/<GUID>FFFFFFFF/<name>`: its file's name in lower case, and the GUID of its PDB id as 32 hex digits in lower case, then `FFFFFFFF` (in place of 8's `<GUID><stamp>FFFFFFFF`). Its checksum is the SHA-256 of the PDB with its id's 20 bytes, the GUID and the stamp, set to 0. | SSQP's key of a portable PDB, as `dotnet-symbol` asked for Serilog's from nuget.org's symbol server, with that checksum. |
+| S2 | Every `.pdb` of a symbol package's zip is read as it is pushed or uploaded, staged one at a time (at most 1,000, each at most 256 MiB). One that is not a portable PDB refuses the symbol package with `400 invalid_package`, which names it, and nothing of it is kept. Each PDB is a file of the package's version, with its checksum among its attributes. A symbol package pushed again (under `allow_redeploy`) keeps only its own PDBs; deleting a symbol package deletes its PDBs, and deleting a version every file of it (D4). | 8, and one record of what a PDB is, read once (E1). |
+| S3 | `SymbolChecksum` names SHA-256 checksums (`SHA256:<hex>`, `;` between them); a PDB is served if one of them is its own, or if none is named; else `404`. | As nuget.org's symbol server answers; a debugger that names none still gets what it asks for by its key. |
+| S4 | A proxy with a `symbol_url` asks `<symbol_url>/<name>/<key>/<name>` for a PDB it does not keep, sending the debugger's `SymbolChecksum` (the proxy engine sends a source's own headers with a download, `proxy.Source.headers`); what it is not given is not remembered as missing. A PDB it keeps has its checksum read from it, and a debugger that names another is answered `404` without asking. A proxy without a `symbol_url` has no symbols. A V2 proxy may have one too. | 8; a server that has no file for one checksum may have it for another. |
+| S5 | HTTP Basic with no user name and an API token as the password is the token's owner, as with `__token__`; with anything else, a failed attempt counted against the address. | `dotnet-symbol --authenticated-server-path <token>` sends `:<token>`, as Azure DevOps's clients do. |
+| S6 | A group asks its members in order for a PDB, as the group engine asks for any file (Y10's files a group passes on, and a PDB). | 8. |
+| S7 | A repository's setup has a `Symbols` snippet: the Visual Studio setting, and `dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" <address>symbols/`. | 8: the setup snippet says so. |
+| S8 | The `dotnet` test installs `dotnet-symbol` 10.0.750501 through the proxy of nuget.org, and fetches the PDB of each SDK's package for its DLL from the hosted repository and through the group: the bytes its symbol package has. | Section 10's `dotnet-symbol`. |
+
 ## 5. Hosted repositories
 
 - **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
@@ -237,7 +250,7 @@ A group's members are in order. It serves V3 from those that speak V3, and V2 fr
 
 ## 8. The symbol server
 
-- **At push of a `.snupkg`:** each `.pdb` in it must be a portable PDB (metadata signature `BSJB`); a Windows PDB, or a `.pdb` that is neither, is refused with `400 invalid_package`, as nuget.org refuses it. Its PDB id (a GUID and a stamp, from the `#Pdb` stream) and its checksum (SHA-256 of the file with the id's bytes zeroed, as the debug directory's `PdbChecksum` holds it) are read, and the PDB is kept as an asset of the package's version at `symbols/<name.pdb>/<GUID><stamp>FFFFFFFF/<name.pdb>`, with the name in lower case (SSQP's key for a portable PDB). Deleting the version deletes it (D4).
+- **At push of a `.snupkg`:** each `.pdb` in it must be a portable PDB (metadata signature `BSJB`); a Windows PDB, or a `.pdb` that is neither, is refused with `400 invalid_package`, as nuget.org refuses it. Its PDB id (a GUID and a stamp, from the `#Pdb` stream) and its checksum (SHA-256 of the file with the id's bytes zeroed, as the debug directory's `PdbChecksum` holds it) are read, and the PDB is kept as an asset of the package's version at `symbols/<name.pdb>/<GUID>FFFFFFFF/<name.pdb>` (S1), with the name in lower case (SSQP's key for a portable PDB). Deleting the version deletes it (D4).
 - **Serving:** `GET symbols/…` reads that asset under the repository's `read` permission. A client that sends `SymbolChecksum` (Visual Studio and `dotnet-symbol` do) is served the PDB only if one of the checksums it names is the PDB's; otherwise `404`, as nuget.org's symbol server answers.
 - **A proxy with `symbol_url`** passes `symbols/…` on to `<symbol_url>/…` with the client's `SymbolChecksum`, and keeps what it is given for good. A proxy without one answers `404` there.
 - **A group** asks its members for a `symbols/…` path in order.
```

- [ ] **Step 2: Run every suite**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3884 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; this plan changes nothing there.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, Task 4's among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 13f settled"
```
