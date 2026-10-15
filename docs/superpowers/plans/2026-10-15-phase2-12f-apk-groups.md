# apk Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One group address, signed with one RSA key of the group's own, serves the indexes of its apk members, your own packages and Alpine's mirror alike, after checking each mirror's signature for the client: a machine trusts that one key and nothing else.

**Architecture:** A group finds, for each directory a client asks for, the members that have an `APKINDEX.tar.gz` there. A proxy's index is checked with the RSA keys its remote was given (`remote_keys`, PEM, as `/etc/apk/keys` holds them); a member that fails is left out and says why. A directory one member has is that member's index, its second stream signed again with the group's key; a directory several have gets an index of the group's own, the members' records in order and of a name and version the first's alone. What a group writes is kept in plan 12a's cache by a digest of its members' state, written behind the requests, one at a time, as plan 12d's YUM groups are.

**Tech Stack:** Python 3.13, FastAPI, `cryptography`; pytest; `alpine:3.24` with jq and curl for the guide's commands, and apk on Alpine 3.24 and 3.23 for the real-client tests.

**Spec:** [docs/superpowers/specs/2026-10-14-linux-package-formats-design.md](../specs/2026-10-14-linux-package-formats-design.md), sections 4.2, 4.4, 4.5, 7.4, 9, 10 and the row of plan 12f in section 12, with what plans 12a to 12e settled (P, Q, R, S and T in section 4).

## Decisions this plan settles

Task 5 writes these into the spec's section 4, as "Settled while building plan 12f".

| # | Decision | Reason |
| --- | --- | --- |
| U1 | An apk proxy's `remote_keys` are RSA public keys, PEM, one or more one after the other, as `/etc/apk/keys/*.rsa.pub` holds them; anything else, or a private key, is refused with `422` at `format_config.remote_keys`. A proxy without them cannot be a member of a group (`422` at `group.members`), as an APT proxy cannot (Q5). | Spec 4.5 and 7.4. |
| U2 | A proxy member's index is checked as apk checks it: one of its `remote_keys` must have signed its second stream, with SHA-1 (`.SIGN.RSA.`) or SHA-256 (`.SIGN.RSA256.`). An index not signed, or signed in another way, is left out. | Alpine signs with SHA-1; abuild-sign can sign with either. |
| U3 | A directory one member has is that member's index: its second stream, as the member wrote it, signed again with the group's key. | What apk reads is what the member's own signature vouched for. |
| U4 | Where several members have a directory, the group writes an index of its own: the members' records as they wrote them, in their order, and of a name and version the first member's alone (in place of 7.4's "name, version and architecture": in one directory, a name and version is the one file apk asks for). Its `DESCRIPTION` is `MegooArti <group>`, and its files' times are 0, so that every process writes the same bytes but for the signature. | Packages are asked of the members in order: a later member's package of the same name and version could not be fetched through the group. |
| U5 | A hosted member's directory without packages adds nothing where another member has the directory, as in a YUM group (S5); a group with a hosted member serves an empty index for a directory no member has packages in. | A machine can be set up before anything is uploaded. |
| U6 | An apk group writes as YUM's do: behind the requests, one writing of a directory at a time (S10), the last whole index kept only while a member it had cannot be checked (S11), and why a member was left out said once its checks are done, and committed (S12). | The lessons of plans 12b and 12d. |

**Changed after the whole-branch review.** The task bodies below show the code as the tasks made it. The branch differs from them as follows; each change was made test-first, and the spec's section 4 records what they settle as U7 to U9.

| # | Change | Reason |
| --- | --- | --- |
| F1 | `index._files` and `packages._members` open their tar with `mode="r:"`. | C1: a nested compressed tar was unpacked without a bound, before the signature was checked. |
| F2 | `docs/formats/apk.md` and `test_apk_client.py`'s `GUIDE`: Alpine's keys from `/usr/share/apk/keys`. | I2: the machine's own keys left other architectures' directories without the mirror. |
| F3 | `groups._filled`, and `_EMPTY`: a directory no member may list packages in is written as the group's one empty index. | I3: an index kept and signed for every name asked. |

## Global Constraints

- **A client trusts the group's key and nothing else**: nothing a proxy member gave is signed by the group unless one of its remote's keys signed it first.
- **What is read of a member is bounded** (spec 9): a proxy's index at 256 MiB packed and 1 GiB unpacked.
- **A format never touches a table or a file**: a group works through its members' contexts, `proxy.ensure_cached`, and `checks.leave_out`.
- **Every test of a stack is marked `docker`.** The guide's commands for a proxy given Alpine's keys are run by one, against the stack.
- **A table's line under its headings is `| --- | --- |`.** Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **Members' records that are unusual**: a record with lines apk does not know, a record without `P` or `V`, two records of one name and version within one member, a member's index whose records are not in its own order, a record long enough to stop apk (T10's bound holds for hosted packages, not for a mirror's).
2. **Large members**: Alpine's `community` for one architecture, two releases' directories, several merges at once, and the groups' budget in the cache.
3. **What a group signs that it did not check**: a hosted member's index, a member that is a group, a proxy whose remote's index and packages change between two requests.
4. **Keys**: Alpine's keys given in another form (one per file, with comments), a remote that rotates its key, a group's key replaced while machines keep the old one under the same name.
5. **The members' order**: a member taken out of the group while its index is kept, a member offline, a package that a later member has and an earlier member's index names but its store lacks.

---

### Task 1: A remote's RSA keys, and checking what they signed

**Files:**
- Modify: `backend/src/megooarti/repositories/signing.py`, `backend/src/megooarti/repositories/checks.py`
- Modify (tests): `backend/tests/repositories/test_signing.py`

**Interfaces:**
- Consumes: plan 12e's `signing.KeysUnusable`, `signing.Unverified`, `signing.PUBLIC_KEYS_MOST`, `signing.generate_rsa`; plan 12d's `checks.remote_keys_setting`.
- Produces: `signing.read_rsa_public_keys(text) -> list[RSAPublicKey]` (raises `KeysUnusable`), `signing.verify_rsa(data, signature, keys, *, sha256=False)` (raises `Unverified`); `checks.remote_keys_setting(config, format_label, read=signing.read_public_keys)`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/test_signing.py`:

```diff
@@ -471,3 +471,42 @@ def test_an_rsa_signer_reads_its_key_only_when_it_first_signs(monkeypatch):
     signer.sign(b"b")
 
     assert loaded == [True]  # once, and without checking again what was checked when kept
+
+
+# --- A remote's RSA keys, for groups of apk repositories -------------------------------
+
+APK_DATA = DATA.parent.parent / "apk/data"
+
+
+def test_a_remotes_rsa_keys_are_read_from_pem_text():
+    builder = (APK_DATA / "builder-6ad0887f.rsa.pub").read_text(encoding="utf-8")
+    another = signing.generate_rsa().public_key
+
+    assert len(signing.read_rsa_public_keys(builder + another)) == 2
+
+
+@pytest.mark.parametrize(
+    ("make", "said"),
+    [
+        (lambda: "not a key", "not one or more RSA public keys"),
+        (lambda: signing.generate_rsa().private_key, "private key"),
+        (
+            lambda: (
+                ec.generate_private_key(ec.SECP256R1())
+                .public_key()
+                .public_bytes(
+                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
+                )
+                .decode()
+            ),
+            "another kind",
+        ),
+        (
+            lambda: "-----BEGIN PUBLIC KEY-----\nbroken\n-----END PUBLIC KEY-----\n",
+            "cannot be read",
+        ),
+    ],
+)
+def test_text_that_is_not_rsa_public_keys_is_refused(make, said):
+    with pytest.raises(signing.KeysUnusable, match=said):
+        signing.read_rsa_public_keys(make())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_signing.py -q`
Expected: 5 failed, 38 passed: `signing` has no `read_rsa_public_keys` (nor `verify_rsa`).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/signing.py`:

```diff
@@ -17,7 +17,7 @@ from dataclasses import dataclass
 
 import pysequoia
 import structlog
-from cryptography.exceptions import UnsupportedAlgorithm
+from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
 from cryptography.hazmat.primitives import hashes, serialization
 from cryptography.hazmat.primitives.asymmetric import padding, rsa
 from sqlalchemy import select, update
@@ -178,6 +178,48 @@ def verify_detached(data: bytes, signature: bytes, certificates: list[object]) -
         ) from None
 
 
+_PUBLIC_PEM = "-----BEGIN PUBLIC KEY-----"
+
+
+def read_rsa_public_keys(text: str) -> list[rsa.RSAPublicKey]:
+    """The RSA public keys in PEM text, as apk keeps them: a remote's, which a group checks
+    it with. One or more, one after the other.
+
+    Raises KeysUnusable for text that has none, is too long, or holds a private key.
+    """
+    if len(text.encode()) > PUBLIC_KEYS_MOST:
+        raise KeysUnusable("The keys are longer than this server keeps.")
+    if "PRIVATE KEY" in text:
+        raise KeysUnusable("This holds a private key. Give the public keys only.")
+    keys = []
+    for part in text.split(_PUBLIC_PEM)[1:]:
+        try:
+            key = serialization.load_pem_public_key((_PUBLIC_PEM + part).encode())
+        except (ValueError, UnsupportedAlgorithm):
+            raise KeysUnusable("A key of these cannot be read as a PEM public key.") from None
+        if not isinstance(key, rsa.RSAPublicKey):
+            raise KeysUnusable("apk's keys are RSA; one of these is another kind.")
+        keys.append(key)
+    if not keys:
+        raise KeysUnusable("This is not one or more RSA public keys, PEM.")
+    return keys
+
+
+def verify_rsa(
+    data: bytes, signature: bytes, keys: list[rsa.RSAPublicKey], *, sha256: bool = False
+) -> None:
+    """Raise Unverified unless one of the keys made this signature of `data`, as
+    `abuild-sign` makes one: PKCS#1 v1.5, with SHA-1, or SHA-256 where said."""
+    digest = hashes.SHA256() if sha256 else hashes.SHA1()
+    for key in keys:
+        try:
+            key.verify(signature, data, padding.PKCS1v15(), digest)
+            return
+        except (InvalidSignature, ValueError):
+            continue
+    raise Unverified("none of the keys made its signature")
+
+
 def signs(repository: Repository) -> str | None:
     """The kind of key this repository signs with, or None if it signs nothing.
 
```

Change `backend/src/megooarti/repositories/checks.py`:

```diff
@@ -7,7 +7,7 @@ last error until it next reaches its remote.
 """
 
 import uuid
-from collections.abc import Sequence
+from collections.abc import Callable, Sequence
 from typing import Any
 
 import structlog
@@ -31,8 +31,15 @@ def remote_keys(member: RepositoryContext) -> str:
     return member.repository.config.get("format_config", {}).get("remote_keys") or ""
 
 
-def remote_keys_setting(config: dict[str, Any], format_label: str) -> dict[str, Any]:
-    """A proxy's settings: its remote's public keys, which a group checks it with."""
+def remote_keys_setting(
+    config: dict[str, Any],
+    format_label: str,
+    read: Callable[[str], object] = signing.read_public_keys,
+) -> dict[str, Any]:
+    """A proxy's settings: its remote's public keys, which a group checks it with.
+
+    `read` is what reads the format's kind of key: OpenPGP's unless said.
+    """
 
     def invalid(field: str, message: str) -> ApiError:
         details = [{"field": field, "message": message}]
@@ -43,11 +50,11 @@ def remote_keys_setting(config: dict[str, Any], format_label: str) -> dict[str,
         raise invalid(f"format_config.{unknown[0]}", f"This is not a setting of {format_label}.")
     keys = config.get("remote_keys") or ""
     if not isinstance(keys, str):
-        raise invalid("format_config.remote_keys", "The keys are armoured text.")
+        raise invalid("format_config.remote_keys", "The keys are text.")
     if not keys.strip():
         return {}
     try:
-        signing.read_public_keys(keys)
+        read(keys)
     except signing.KeysUnusable as error:
         raise invalid("format_config.remote_keys", str(error)) from None
     return {"remote_keys": keys}
```

- [ ] **Step 4: Run the tests to verify they pass**

APT's and YUM's proxies take their keys through the same setting: their tests are run as well, unchanged.

Run (in `backend/`): `uv run pytest tests/repositories/test_signing.py tests/repositories/apt tests/repositories/yum -q`
Expected: 442 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "feat: a remote's RSA keys, PEM, and a check of what they signed as abuild-sign signs"
```

---

### Task 2: Reading a member's index, and merging members' records

**Files:**
- Modify: `backend/src/megooarti/repositories/apk/index.py`, `backend/tests/repositories/apk/test_index.py`

**Interfaces:**
- Consumes: Task 1's `signing.read_rsa_public_keys`, `signing.verify_rsa`; plan 12e's `data/APKINDEX.tar.gz` and `data/builder-6ad0887f.rsa.pub`.
- Produces: `index.UNPACKED_MOST`, `index.InvalidIndex`, `index.Read(key_name, sha256, signature, packed, text)`, `index.read(data, most=UNPACKED_MOST) -> Read`, `index.merged(texts) -> str`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/apk/test_index.py`:

```diff
@@ -1,5 +1,6 @@
 """A directory's `APKINDEX.tar.gz`, written as apk-tools 3's `apk index` writes it."""
 
+import gzip
 import io
 import tarfile
 import zlib
@@ -104,3 +105,63 @@ def test_an_empty_index_lists_nothing(key):
     data = index.index_file([], "", "d", "k.rsa.pub", signing.RsaSigner(key.private_key), 1)
 
     assert apkindex(data) == ""
+
+
+def test_an_index_abuild_wrote_reads_back_whole():
+    read = index.read((DATA / "APKINDEX.tar.gz").read_bytes())
+
+    assert (read.key_name, read.sha256) == ("builder-6ad0887f.rsa.pub", False)
+    assert read.text == apkindex((DATA / "APKINDEX.tar.gz").read_bytes())
+    assert len(read.signature) == 512
+
+
+@pytest.mark.parametrize(
+    ("data", "reason"),
+    [
+        (b"not gzip", "not gzip streams"),
+        (gzip.compress(b"x" * 100, mtime=0), "not a tar archive"),
+        ((DATA / "APKINDEX.tar.gz").read_bytes()[:700], "ends early"),
+    ],
+)
+def test_what_is_not_an_index_a_group_can_read_is_refused(data, reason):
+    with pytest.raises(index.InvalidIndex, match=reason):
+        index.read(data)
+
+
+def test_an_index_larger_unpacked_than_the_bound_is_refused():
+    with pytest.raises(index.InvalidIndex, match="larger unpacked"):
+        index.read((DATA / "APKINDEX.tar.gz").read_bytes(), most=1000)
+
+
+def test_members_records_are_merged_an_earlier_members_first():
+    first = "C:Q1a\nP:hello\nV:1.0-r0\nA:x86_64\n\nC:Q1b\nP:tool\nV:1.0-r0\nA:x86_64\n\n"
+    later = (
+        "C:Q1c\nP:hello\nV:1.0-r0\nA:x86_64\n\n"  # the same file apk would ask for
+        "C:Q1d\nP:hello\nV:2.0-r0\nA:x86_64\n\n"
+        "C:Q1e\nA:x86_64\n\n"  # names no package
+    )
+
+    merged = index.merged([first, later])
+
+    assert [line for line in merged.splitlines() if line.startswith("C:")] == [
+        "C:Q1a",
+        "C:Q1b",
+        "C:Q1d",
+    ]
+    assert merged.endswith("\n\n")
+
+
+def test_an_index_abuild_signed_is_checked_with_its_key_and_no_other():
+    read = index.read((DATA / "APKINDEX.tar.gz").read_bytes())
+    builder = signing.read_rsa_public_keys(
+        (DATA / "builder-6ad0887f.rsa.pub").read_text(encoding="utf-8")
+    )
+    another = signing.read_rsa_public_keys(signing.generate_rsa().public_key)
+
+    signing.verify_rsa(read.packed, read.signature, another + builder)
+    with pytest.raises(signing.Unverified):
+        signing.verify_rsa(read.packed, read.signature, another)
+    with pytest.raises(signing.Unverified):
+        signing.verify_rsa(read.packed + b"x", read.signature, builder)
+    with pytest.raises(signing.Unverified):
+        signing.verify_rsa(read.packed, read.signature, builder, sha256=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/apk/test_index.py -q`
Expected: 7 failed, 7 passed: `index` has no `read`, `InvalidIndex` or `merged`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/apk/index.py`:

```diff
@@ -11,7 +11,9 @@ at `<repository>/<architecture>/<name>-<version>.apk`, by what the index says.
 """
 
 import gzip
+import io
 import tarfile
+import zlib
 from collections.abc import Sequence
 from dataclasses import dataclass
 from typing import Protocol
@@ -121,3 +123,91 @@ def index_file(
     """A whole `APKINDEX.tar.gz`, signed."""
     packed = archive(description, apkindex(listed, architecture), moment)
     return signature(packed, key_name, signer, moment) + packed
+
+
+# --- What a group reads of its members' indexes ----------------------------------------
+
+# The most of a member's index that is read unpacked (spec 9).
+UNPACKED_MOST = 1024 * 1024 * 1024
+_SIGNED = {".SIGN.RSA.": False, ".SIGN.RSA256.": True}  # by its prefix: whether SHA-256
+
+
+class InvalidIndex(ValueError):
+    """Bytes that are not an `APKINDEX.tar.gz` a group can read."""
+
+
+@dataclass(frozen=True)
+class Read:
+    """What an index is: who signed it and how, its second stream, and its records."""
+
+    key_name: str  # of the key it says signed it; empty if it is not signed
+    sha256: bool  # whether its signature is of SHA-256 (`.SIGN.RSA256.`) or SHA-1
+    signature: bytes
+    packed: bytes  # the stream it signs, as it is packed
+    text: str  # APKINDEX
+
+
+def _stream(data: bytes, most: int) -> tuple[bytes, bytes, bytes]:
+    """The first gzip stream of `data`, packed and unpacked, and what follows it."""
+    unpack = zlib.decompressobj(wbits=31)
+    try:
+        opened = unpack.decompress(data, most + 1)
+    except zlib.error:
+        raise InvalidIndex("it is not gzip streams, as an APKINDEX.tar.gz is") from None
+    if len(opened) > most or unpack.unconsumed_tail:
+        raise InvalidIndex("it is larger unpacked than this server reads")
+    if not unpack.eof:
+        raise InvalidIndex("it ends early")
+    rest = unpack.unused_data
+    return data[: len(data) - len(rest)], opened, rest
+
+
+def _files(opened: bytes) -> dict[str, bytes]:
+    try:
+        with tarfile.open(fileobj=io.BytesIO(opened + b"\0" * 1024)) as tar:
+            return {
+                member.name: tar.extractfile(member).read()
+                for member in tar.getmembers()
+                if member.isfile()
+            }
+    except (tarfile.TarError, ValueError, OverflowError):
+        raise InvalidIndex("a part of it is not a tar archive") from None
+
+
+def read(data: bytes, most: int = UNPACKED_MOST) -> Read:
+    """What an `APKINDEX.tar.gz` says, and of its signature. Raises InvalidIndex."""
+    packed, opened, rest = _stream(data, most)
+    first = _files(opened)
+    signed = [name for name in first if name.startswith(".SIGN.")]
+    key_name, sha256, signature = "", False, b""
+    if signed:
+        name = signed[0]
+        prefix = next((p for p in _SIGNED if name.startswith(p)), None)
+        if prefix is None:
+            raise InvalidIndex(f"it is signed in a way this server cannot check ({name})")
+        key_name, sha256, signature = name.removeprefix(prefix), _SIGNED[prefix], first[name]
+        packed, opened, _ = _stream(rest, most)
+        first = _files(opened)
+    if "APKINDEX" not in first:
+        raise InvalidIndex("it has no APKINDEX")
+    try:
+        text = first["APKINDEX"].decode("utf-8")
+    except UnicodeDecodeError:
+        raise InvalidIndex("its APKINDEX is not UTF-8") from None
+    return Read(key_name, sha256, signature, packed, text)
+
+
+def merged(texts: Sequence[str]) -> str:
+    """Members' `APKINDEX`, in their order: of a name and version in a directory (the
+    file apk would ask for), the first member's record alone."""
+    seen: set[tuple[str, str]] = set()
+    kept = []
+    for text in texts:
+        for record in text.split("\n\n"):
+            fields = dict(line.split(":", 1) for line in record.splitlines() if line[1:2] == ":")
+            named = (fields.get("P", ""), fields.get("V", ""))
+            if not all(named) or named in seen:
+                continue
+            seen.add(named)
+            kept.append(record.strip("\n") + "\n\n")
+    return "".join(kept)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/apk/test_index.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/apk backend/tests/repositories/apk
git commit -m "feat: read a member's APKINDEX and its signature, and merge members' records, the earlier first"
```

---

### Task 3: Groups of apk repositories

**Files:**
- Create: `backend/src/megooarti/repositories/apk/groups.py`, `backend/tests/repositories/apk/test_groups.py`
- Modify: `backend/src/megooarti/repositories/apk/format.py`, `docs/formats/apk.md`
- Modify (tests): `backend/tests/repositories/apk/conftest.py`, `test_hosted.py`

**Interfaces:**
- Consumes: Tasks 1 and 2; plan 12e's `format.hosted_indexes`, `format.index_file`, `format.description_of`, `index.archive`, `index.signature`, `paths.*`; plan 12d's `checks.leave_out`, `checks.members_in`, `checks.remote_keys`, `derived.Written.members`, `derived.written(..., stale=True)`.
- Produces: the `apk` format's types are hosted, proxy and group; an apk proxy's `format_config.remote_keys`; `format.holds_packages(written, directory) -> bool`; `groups.RETRY`, `groups.handle_group(context, request, path, serve)`, and `groups._written(offers, description, key_name, signer)`, which a test counts. In the tests, `conftest.mirror_files(directory, packages_by_name, *, key=, root=)`, `mirror_key()`, `written_behind()`, `ROOT`, `MIRROR_KEY`.

- [ ] **Step 1: Write the failing tests**

Two tests of plan 12e change: an apk proxy now takes `remote_keys` (so text that is not keys is refused at `format_config.remote_keys`), and an apk group can be made.

Change `backend/tests/repositories/apk/conftest.py`:

```diff
@@ -1,12 +1,15 @@
-"""apk repositories made for a test, and what uploads to them."""
+"""apk repositories made for a test, what uploads to them, and a mirror to proxy."""
 
+import asyncio
 import functools
 
 import pytest
 
 from megooarti.repositories import derived, service, signing
+from megooarti.repositories.apk import index, packages
 from megooarti.repositories.models import Repository
 from tests.accounts import PASSWORD, basic
+from tests.repositories.apk.packages import pieces
 
 URL = "/repository/apk-hosted"
 MAIN = f"{URL}/v3.24/main"
@@ -21,6 +24,7 @@ async def create(
     type: str = "hosted",
     hosted: dict | None = None,
     proxy: dict | None = None,
+    group: dict | None = None,
     format_config: dict | None = None,
 ) -> Repository:
     """An apk repository, committed."""
@@ -33,6 +37,7 @@ async def create(
         blob_store="default",
         hosted=hosted,
         proxy=proxy,
+        group=group,
         format_config=format_config or {},
     )
     await db.commit()
@@ -54,6 +59,15 @@ def quick_keys(monkeypatch):
     monkeypatch.setattr(signing, "generate_rsa", rsa_key)
 
 
+async def written_behind() -> None:
+    """Wait for what a group writes behind its requests, as the next request would find it.
+
+    In the tests every session shares one connection, which two cannot use at once.
+    """
+    while derived._writing:
+        await asyncio.gather(*list(derived._writing.values()), return_exceptions=True)
+
+
 @pytest.fixture(autouse=True)
 def nothing_kept():
     """Every test writes its indexes anew: what one wrote is not served to the next."""
@@ -76,3 +90,38 @@ async def root(make_user) -> dict[str, str]:
 async def upload(client, headers, path: str, package: bytes, *, repository: str = "apk-hosted"):
     """A package sent as `curl --upload-file` sends it to its path."""
     return await client.put(f"/repository/{repository}/{path}", content=package, headers=headers)
+
+
+# --- A mirror, as a proxy's remote --------------------------------------------------
+
+ROOT = REMOTE.removeprefix("http://remote.test/")
+MIRROR_KEY = "alpine-devel@lists.alpinelinux.org-test.rsa.pub"
+
+
+@functools.cache
+def mirror_key() -> signing.Material:
+    """The key the stand-in mirror signs with, made once for every test."""
+    return _GENERATE()
+
+
+async def mirror_files(
+    directory: str,
+    packages_by_name: dict[str, bytes],
+    *,
+    key: signing.Material | None = None,
+    root: str = ROOT,
+) -> dict[str, bytes]:
+    """A mirror's directory, as the stand-in remote serves it, by path under its host:
+    the packages, by their file names, and their index, signed with `key`."""
+    listed = [
+        index.Listed(len(data), await packages.read(pieces(data)))
+        for data in packages_by_name.values()
+    ]
+    signer = signing.RsaSigner((key or mirror_key()).private_key)
+    architecture = directory.rpartition("/")[2]
+    data = index.index_file(listed, architecture, "v3.24.2", MIRROR_KEY, signer, 1792000000)
+    files = {f"{root}/{directory}/{index.INDEX}": data}
+    files.update(
+        {f"{root}/{directory}/{name}": package for name, package in packages_by_name.items()}
+    )
+    return files
```

Create `backend/tests/repositories/apk/test_groups.py`:

```python
"""A group of apk repositories: one address and one key for its members' indexes."""

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from megooarti.repositories import signing
from megooarti.repositories.apk import groups as apk_groups
from megooarti.repositories.apk import index
from tests.accounts import error_code
from tests.repositories.apk.conftest import (
    REMOTE,
    ROOT,
    create,
    mirror_files,
    mirror_key,
    upload,
    written_behind,
)
from tests.repositories.apk.packages import DATA, REAL, make_apk, pkginfo

GROUP = "/repository/apk-public"
X86 = "v3.24/main/x86_64"
KEY = "megooarti-apk-public.rsa.pub"
HELLO = "megooarti-hello-1.0-r0.apk"
OURS = make_apk()
THEIRS = make_apk(pkginfo(description="The mirror's own"))
# The mirror's packages: one an earlier member has too, and one of its own.
MIRRORED = {HELLO: THEIRS, REAL[1]: (DATA / REAL[1]).read_bytes()}


def opened(data: bytes, public_key: bytes) -> index.Read:
    """An index, its signature checked with one public key. Raises if it does not hold."""
    read = index.read(data)
    key = serialization.load_pem_public_key(public_key)
    key.verify(read.signature, read.packed, padding.PKCS1v15(), hashes.SHA1())
    return read


def names(read: index.Read) -> list[tuple[str, str]]:
    found = []
    for record in read.text.split("\n\n"):
        said = dict(line.split(":", 1) for line in record.splitlines() if line[1:2] == ":")
        if said:
            found.append((said["P"], said["T"]))
    return found


@pytest.fixture
async def mirror(fake_remote):
    """A mirror whose x86_64 directory has two packages, its index signed by its key."""
    fake_remote.files.update(await mirror_files(X86, MIRRORED))
    return fake_remote


async def a_proxy(db, keys: str | None = None):
    return await create(
        db,
        "apk-alpine",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
        format_config={"remote_keys": mirror_key().public_key if keys is None else keys},
    )


async def a_group(db, *members: str):
    return await create(db, "apk-public", type="group", group={"members": list(members)})


async def group_index(client, root, directory: str = X86) -> index.Read:
    data = (await client.get(f"{GROUP}/{directory}/APKINDEX.tar.gz", headers=root)).content
    key = (await client.get(f"{GROUP}/{KEY}", headers=root)).content
    return opened(data, key)


async def test_a_directory_one_member_has_is_its_index_signed_again_with_the_groups_key(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"v3.23/main/x86_64/{HELLO}", OURS)

    ours = await group_index(client, root, "v3.23/main/x86_64")
    theirs = await group_index(client, root)

    hosted = index.read(
        (
            await client.get(
                f"/repository/apk-hosted/v3.23/main/x86_64/{index.INDEX}", headers=root
            )
        ).content
    )
    mirrored = index.read(mirror.files[f"{ROOT}/{X86}/{index.INDEX}"])
    assert (ours.packed, ours.key_name) == (hosted.packed, KEY)
    assert (theirs.packed, theirs.key_name) == (mirrored.packed, KEY)


async def test_a_directory_several_members_have_is_merged_an_earlier_members_package_first(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    merged = await group_index(client, root)

    assert names(merged) == [("megooarti-hello", "Says hello"), ("yash-binsh", "yash as /bin/sh")]


async def test_a_package_comes_from_the_first_member_that_has_it(client, db, root, mirror):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    ours = await client.get(f"{GROUP}/{X86}/{HELLO}", headers=root)
    theirs = await client.get(f"{GROUP}/{X86}/{REAL[1]}", headers=root)

    assert ours.content == OURS
    assert theirs.content == MIRRORED[REAL[1]]


async def test_a_proxy_whose_index_its_keys_did_not_sign_is_left_out(client, db, root, fake_remote):
    another = signing.generate_rsa()
    fake_remote.files.update(await mirror_files(X86, MIRRORED, key=another))
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    merged = await group_index(client, root)
    shown = (await client.get("/api/v1/repositories/apk-alpine", headers=root)).json()

    assert [name for name, _ in names(merged)] == ["megooarti-hello"]
    assert shown["status"]["last_error"].startswith("Left out of the group apk-public:")
    assert "not signed by its remote's keys" in shown["status"]["last_error"]


async def test_a_proxy_without_its_remotes_keys_cannot_be_a_member(admin_client):
    for body in (
        {"name": "apk-hosted", "format": "apk", "type": "hosted"},
        {"name": "apk-alpine", "format": "apk", "type": "proxy", "proxy": {"remote_url": REMOTE}},
    ):
        assert (await admin_client.post("/api/v1/repositories", json=body)).status_code == 201

    refused = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apk-public",
            "format": "apk",
            "type": "group",
            "group": {"members": ["apk-hosted", "apk-alpine"]},
        },
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "group.members"


async def test_the_merged_index_is_written_once_for_each_state_of_the_members(
    client, db, root, mirror, monkeypatch
):
    written = []
    write = apk_groups._written

    def counted(*arguments):
        written.append(1)
        return write(*arguments)

    monkeypatch.setattr(apk_groups, "_written", counted)
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    assert len(written) == 1
    await upload(
        client, root, f"{X86}/megooarti-tool-1.0-r0.apk", make_apk(pkginfo(name="megooarti-tool"))
    )
    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)  # written again, behind
    await written_behind()
    assert len(written) == 2
    again = await group_index(client, root)
    assert "megooarti-tool" in [name for name, _ in names(again)]


async def test_while_a_member_it_had_cannot_be_checked_the_last_whole_index_is_kept(
    client, db, root, mirror, monkeypatch
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)
    whole = (await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)).content
    good = mirror.files[f"{ROOT}/{X86}/{index.INDEX}"]
    mirror.files[f"{ROOT}/{X86}/{index.INDEX}"] = b"not an index"

    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await written_behind()
    held = (await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)).content
    mirror.files[f"{ROOT}/{X86}/{index.INDEX}"] = good
    monkeypatch.setattr(apk_groups, "RETRY", timedelta(0))
    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await written_behind()
    again = await group_index(client, root)

    assert held == whole
    assert "yash-binsh" in [name for name, _ in names(again)]


async def test_a_member_added_that_cannot_be_checked_does_not_keep_the_others_still(
    client, db, root, fake_remote
):
    fake_remote.files.update(await mirror_files(X86, MIRRORED, key=signing.generate_rsa()))
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted")
    await upload(client, root, f"{X86}/{HELLO}", OURS)
    await group_index(client, root)
    changed = await client.put(
        "/api/v1/repositories/apk-public",
        json={"group": {"members": ["apk-hosted", "apk-alpine"]}},
        headers=root,
    )
    assert changed.status_code == 200, changed.text
    await upload(
        client, root, f"{X86}/megooarti-tool-1.0-r0.apk", make_apk(pkginfo(name="megooarti-tool"))
    )

    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await written_behind()
    found = await group_index(client, root)

    assert [name for name, _ in names(found)] == ["megooarti-hello", "megooarti-tool"]


async def test_a_hosted_member_without_packages_adds_nothing_to_a_mirrors_directory(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")

    found = await group_index(client, root)

    assert found.packed == index.read(mirror.files[f"{ROOT}/{X86}/{index.INDEX}"]).packed


async def test_a_group_of_members_without_packages_has_an_empty_index(client, db, root):
    await create(db)
    await a_group(db, "apk-hosted")

    found = await group_index(client, root, "v3.24/main/riscv64")

    assert found.text == ""


async def test_a_proxys_remote_keys_are_kept_and_shown(admin_client):
    keys = mirror_key().public_key + (DATA / "builder-6ad0887f.rsa.pub").read_text(encoding="utf-8")

    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apk-alpine",
            "format": "apk",
            "type": "proxy",
            "proxy": {"remote_url": REMOTE},
            "format_config": {"remote_keys": keys},
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["format_config"] == {"remote_keys": keys}


@pytest.mark.parametrize(
    ("keys", "said"),
    [
        ("not a key", "not one or more RSA public keys"),
        (mirror_key().private_key, "private key"),
        (
            (DATA.parent.parent / "apt/data/plain-rsa.pub.asc").read_text(encoding="utf-8"),
            "not one",
        ),
    ],
)
async def test_keys_apk_cannot_check_with_are_refused(admin_client, keys, said):
    refused = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apk-alpine",
            "format": "apk",
            "type": "proxy",
            "proxy": {"remote_url": REMOTE},
            "format_config": {"remote_keys": keys},
        },
    )

    assert refused.status_code == 422
    detail = refused.json()["error"]["details"][0]
    assert detail["field"] == "format_config.remote_keys"
    assert said in detail["message"]
```

Change `backend/tests/repositories/apk/test_hosted.py`:

```diff
@@ -268,24 +268,19 @@ async def test_a_repository_is_read_with_the_right_to_read(client, db, hosted, m
     ("type", "format_config", "field"),
     [
         ("hosted", {"suite": "stable"}, "format_config"),
-        ("proxy", {"remote_keys": "x"}, "format_config"),
+        ("proxy", {"remote_keys": "x"}, "format_config.remote_keys"),
+        ("proxy", {"suite": "x"}, "format_config.suite"),
+        ("group", {"suite": "x"}, "format_config"),
     ],
 )
 async def test_settings_that_cannot_be_used_are_refused(admin_client, type, format_config, field):
     body = {"name": "apk", "format": "apk", "type": type, "format_config": format_config}
     if type == "proxy":
         body["proxy"] = {"remote_url": "https://dl-cdn.alpinelinux.org/alpine"}
+    if type == "group":
+        body["group"] = {"members": []}
 
     refused = await admin_client.post("/api/v1/repositories", json=body)
 
     assert refused.status_code == 422
     assert refused.json()["error"]["details"][0]["field"] == field
-
-
-async def test_a_group_of_apk_repositories_is_not_made_yet(admin_client):
-    refused = await admin_client.post(
-        "/api/v1/repositories",
-        json={"name": "apk-all", "format": "apk", "type": "group", "group": {"members": []}},
-    )
-
-    assert refused.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/apk -q`
Expected: 1 error during collection: `megooarti.repositories.apk` has no `groups`.

- [ ] **Step 3: Write the code and the guide**

Create `backend/src/megooarti/repositories/apk/groups.py`:

```python
"""Groups of apk repositories: one address, one key, for the indexes of all the members.

A group serves an `APKINDEX.tar.gz` in each directory where a member has one: a hosted
member in a directory where it holds packages, a proxy where its remote has the file.
A client trusts the group's key and nothing else, so the group checks what it signs:
a proxy's index must be signed by one of the keys its remote was given
(`remote_keys`), and a member that fails is left out, its reason logged and kept as
its last error.

A directory one member has is that member's index, its records as the member wrote
them, signed again with the group's key. In a directory several members have, the
group writes an index of its own, an earlier member's record first: of a name and
version, the file apk would ask for, the first member's alone. Packages are asked of
the members in order, as in any group.

What a group writes of a directory is kept, by a digest of what its members' indexes
are now: a hosted member's revision, and a proxy's index and keys. A request does not
wait for the next one while one is kept, and holds no database connection while it
waits for the first; one is written at a time. While a member that the last one had
cannot be checked, the last one is kept a while longer and tried again.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field, replace
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived, group, proxy, signing
from megooarti.repositories.apk import format as apk
from megooarti.repositories.apk import index, paths
from megooarti.repositories.checks import LeftOut, leave_out, members_in, remote_keys
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve
from megooarti.repositories.models import SigningKey

# The most of a proxy member's index, packed, that is read.
PACKED_MOST = 256 * 1024 * 1024
# How long what was written while a member was left out is served before another try.
RETRY = timedelta(minutes=1)
# The mark of a revision written while a member was left out: no digest ends so.
_INCOMPLETE = "~"


@dataclass(frozen=True)
class Offer:
    """What one member has of a directory, checked."""

    member: RepositoryContext
    read: index.Read
    empty: bool  # a hosted member's directory that holds no packages


@dataclass
class _Outcome:
    """Which members a writing left out, and why."""

    left: dict[uuid.UUID, tuple[RepositoryContext, str]] = field(default_factory=dict)


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


async def _token(member: RepositoryContext, directory: str) -> str | None:
    """What a member's index of a directory is now, or None if it has none there."""
    if member.repository.type == "hosted":
        revision, _ = await member.revision()
        return f"{member.repository.id}:{revision}"
    path = paths.in_directory(directory, index.INDEX)
    try:
        await proxy.ensure_cached(member, path)
    except ApiError as error:
        if error.status_code in group.TRY_NEXT:
            return None  # it does not have the directory, or cannot be asked now
        raise
    stored = await member.stat(path)
    if stored is None:
        return None
    keys = hashlib.sha256(remote_keys(member).encode()).hexdigest()
    return f"{member.repository.id}:{stored.sha256}:{keys}"


async def _offer(member: RepositoryContext, directory: str) -> Offer:
    """What a member has of a directory, checked. Raises LeftOut."""
    if member.repository.type == "hosted":
        written = await apk.hosted_indexes(member)
        data = apk.index_file(written, directory)
        read = await asyncio.to_thread(index.read, data)
        return Offer(member, read, not apk.holds_packages(written, directory))
    keys = remote_keys(member)
    if not keys:
        raise LeftOut("it has no keys of its remote to check its index with")
    try:
        data = await member.read(paths.in_directory(directory, index.INDEX), limit=PACKED_MOST)
    except TooLarge:
        raise LeftOut("its index is larger than this server reads") from None
    if data is None:
        raise LeftOut("its index is gone")
    try:
        read = await asyncio.to_thread(index.read, data)
    except index.InvalidIndex as error:
        raise LeftOut(f"its index cannot be read: {error}") from None
    if not read.key_name:
        raise LeftOut("its index is not signed")
    try:
        certificates = signing.read_rsa_public_keys(keys)
        signing.verify_rsa(read.packed, read.signature, certificates, sha256=read.sha256)
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    except signing.Unverified:
        raise LeftOut(
            f"its index is not signed by its remote's keys (it says {read.key_name})"
        ) from None
    return Offer(member, read, False)


async def _offers(
    db: AsyncSession,
    context: RepositoryContext,
    candidates: list[uuid.UUID],
    directory: str,
    outcome: _Outcome,
) -> list[Offer]:
    offers = []
    for member in await members_in(db, context, candidates):
        try:
            offers.append(await _offer(member, directory))
        except LeftOut as error:
            outcome.left.setdefault(member.repository.id, (member, str(error)))
    # A hosted member's directory without packages adds nothing to another's.
    filled = [offer for offer in offers if not offer.empty]
    return filled or offers[:1]


def _written(
    offers: list[Offer], description: str, key_name: str, signer: signing.RsaSigner
) -> derived.Written:
    """The group's index of a directory, signed with its key."""
    if len(offers) == 1:
        # The member's records as it wrote them: its second stream, signed again.
        packed = offers[0].read.packed
    else:
        text = index.merged([offer.read.text for offer in offers])
        packed = index.archive(description, text, 0)
    data = index.signature(packed, key_name, signer, 0) + packed
    members = frozenset(offer.member.repository.id for offer in offers)
    return derived.Written("", utcnow(), {index.INDEX: data}, members=members)


async def _write(
    db: AsyncSession,
    context: RepositoryContext,
    candidates: list[uuid.UUID],
    directory: str,
    key: SigningKey,
    revision: str,
) -> derived.Written:
    """What the group has of a directory, written with a session of its own."""
    of = (context.repository.id, directory)
    now = utcnow()
    previous = derived.peek(of)
    whole = previous is not None and not str(previous.revision).endswith(_INCOMPLETE)
    outcome = _Outcome()
    offers = await _offers(db, context, candidates, directory, outcome)
    for member, reason in outcome.left.values():
        await leave_out(context, member, reason)
    await db.commit()
    # Keep the last whole one while a member it had cannot be checked.
    if whole and outcome.left.keys() & previous.members:
        return replace(previous, held_until=now + RETRY)
    if not offers:
        raise _not_found("No repository of this group that has this directory could be checked.")
    written = await asyncio.to_thread(
        _written,
        offers,
        apk.description_of(context),
        paths.key_name(context.repository.name),
        signing.signer(context.settings, key),
    )
    if outcome.left:
        # Tried again after a while: what was left out may be back.
        return replace(written, revision=revision + _INCOMPLETE, held_until=now + RETRY)
    return replace(written, revision=revision)


async def _directory_index(
    context: RepositoryContext, request: Request, directory: str
) -> derived.Written:
    """What the group has of a directory."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, directory)
        if token is not None:
            candidates.append(member.repository.id)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has an index in this directory.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    said = "\n".join([key.fingerprint, directory, *tokens])
    revision = hashlib.sha256(said.encode()).hexdigest()
    # A request that waits for the writing holds no connection: the writing has its own.
    await context.release()
    sessions = request.app.state.sessionmaker

    async def write() -> derived.Written:
        async with sessions() as db:
            return await _write(db, context, candidates, directory, key, revision)

    of = (context.repository.id, directory)
    return await derived.written(of, revision, write, stale=True)


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """A directory's index from what the group writes; anything else from a member."""
    parsed = paths.classify(path, context.repository.name)
    if request.method not in ("GET", "HEAD") or parsed.kind != "index":
        return await group.handle_group(context, request, path, serve)
    written = await _directory_index(context, request, parsed.directory)
    data = written.files[index.INDEX]
    return context.respond_with(
        data,
        request,
        filename=index.INDEX,
        content_type="application/gzip",
        last_modified=written.changed,
        etag=hashlib.sha256(data).hexdigest(),
        dated=False,
    )
```

Change `backend/src/megooarti/repositories/apk/format.py`:

```diff
@@ -25,12 +25,13 @@ from starlette.requests import Request
 from starlette.responses import Response
 
 from megooarti.errors import ApiError
-from megooarti.repositories import derived, signing
+from megooarti.repositories import checks, derived, signing
 from megooarti.repositories.apk import index, packages, paths, versions
 from megooarti.repositories.content import RepositoryContext, Snapshot
 from megooarti.repositories.formats import (
     ComponentKey,
     Format,
+    Serve,
     Usage,
     declared_hashes,
     declared_size,
@@ -39,6 +40,7 @@ from megooarti.repositories.formats import (
     register,
 )
 from megooarti.repositories.forms import UploadForm
+from megooarti.repositories.models import Repository
 from megooarti.repositories.paths import normalise_path
 from megooarti.storage.backends import StagedBlob
 
@@ -213,6 +215,11 @@ async def hosted_indexes(context: RepositoryContext) -> derived.Written:
     return await derived.written(context.repository.id, revision, write)
 
 
+def holds_packages(written: derived.Written, directory: str) -> bool:
+    """Whether a directory of a revision has packages in its index."""
+    return paths.in_directory(directory, index.INDEX) in written.files
+
+
 def index_file(written: derived.Written, directory: str) -> bytes:
     """A directory's index, from what was written of a revision: an empty one if it has none."""
     found = written.files.get(paths.in_directory(directory, index.INDEX))
@@ -247,12 +254,34 @@ async def _public_key(context: RepositoryContext, request: Request) -> Response:
     )
 
 
+def _invalid_setting(field: str, message: str) -> ApiError:
+    details = [{"field": field, "message": message}]
+    return ApiError(422, "validation_error", "The request is not valid.", details)
+
+
 class ApkFormat(Format):
     name = "apk"
-    types = frozenset({"hosted", "proxy"})
+    types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
     signs = signing.RSA
 
+    def validate_config(
+        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
+    ) -> dict[str, Any]:
+        """A proxy's remote's keys, PEM, which a group checks it with; nothing else."""
+        if repository_type == "proxy":
+            return checks.remote_keys_setting(config, "apk", signing.read_rsa_public_keys)
+        return super().validate_config(repository_type, config, current)
+
+    def validate_member(self, member: Repository) -> None:
+        """A proxy whose signatures a group cannot check is not one of its members."""
+        if member.type == "proxy" and not member.config.get("format_config", {}).get("remote_keys"):
+            raise _invalid_setting(
+                "group.members",
+                f"{member.name} is a proxy without its remote's keys "
+                "(format_config.remote_keys): a group could not check what it signs.",
+            )
+
     def describe_component(
         self, path: str, attributes: dict[str, Any] | None = None
     ) -> ComponentKey | None:
@@ -339,5 +368,15 @@ class ApkFormat(Format):
             return await _index(context, request, parsed)
         raise _not_found()
 
+    async def handle_group(
+        self, context: RepositoryContext, request: Request, path: str, serve: Serve
+    ) -> Response:
+        if paths.classify(path, context.repository.name).kind == "key" and _is_read(request):
+            return await _public_key(context, request)
+        # Imported here: it is written against this module.
+        from megooarti.repositories.apk import groups
+
+        return await groups.handle_group(context, request, path, serve)
+
 
 register(ApkFormat())
```

Change `docs/formats/apk.md`:

````diff
@@ -87,10 +87,66 @@ echo "https://repo.example.com/repository/apk-alpine/v3.24/main" > /etc/apk/repo
 - **A proxy**'s remote is a mirror's root. Each `APKINDEX.tar.gz` is checked again
   with the remote after `metadata_max_age_minutes`; packages never change, and are
   kept.
+- **A proxy's `remote_keys`**, its remote's public keys, PEM, one after the other, are
+  what a group it is a member of checks its indexes with; a proxy that is not in a
+  group does not use them, and apk checks the mirror's signatures itself.
+
+## Groups
+
+A group puts your own repositories and the mirror behind one address, and signs every
+index it serves with a key of its own: a machine needs that one key, and nothing else.
+The group checks for it what apk would have checked, so a proxy can be a member only if
+it has its remote's public keys. Alpine's are on every Alpine machine; on one that has
+jq and curl:
+
+```bash
+keys=$(cat /etc/apk/keys/*.rsa.pub)
+jq -n --arg keys "$keys" '{
+  name: "apk-alpine", format: "apk", type: "proxy",
+  proxy: {remote_url: "https://dl-cdn.alpinelinux.org/alpine"},
+  format_config: {remote_keys: $keys}
+}' | curl -u admin -H 'Content-Type: application/json' -d @- \
+  http://localhost:8000/api/v1/repositories
+
+curl -u admin -H 'Content-Type: application/json' -d '{
+  "name": "apk-public", "format": "apk", "type": "group",
+  "group": {"members": ["apk-hosted", "apk-alpine"]}
+}' http://localhost:8000/api/v1/repositories
+```
+
+On each machine, the group's key, under the name apk finds it by, and the group in
+place of Alpine's mirror:
+
+```bash
+wget -q -O /etc/apk/keys/megooarti-apk-public.rsa.pub \
+  "https://ci:$MEGOOARTI_TOKEN@repo.example.com/repository/apk-public/megooarti-apk-public.rsa.pub"
+echo "https://ci:$MEGOOARTI_TOKEN@repo.example.com/repository/apk-public/v3.24/main" \
+  > /etc/apk/repositories
+```
+
+- **The group serves an index in each directory where a member has one**: a hosted
+  member where it holds packages, a proxy where its remote has `APKINDEX.tar.gz`.
+- **A directory one member has** is that member's index, its records as the member
+  wrote them, signed again with the group's key.
+- **A directory several members have** gets an index of the group's own: the members'
+  records in their order, and of a name and version (the file apk asks for), the first
+  member's alone. Packages are asked of the members in order, as in any group, so a
+  package's file must be the same in every member that has it.
+- **A member is checked before it is used**: a proxy's index must be signed by one of
+  its `remote_keys` (with SHA-1 or SHA-256, as `abuild-sign` signs). A member that
+  fails is left out, it is logged, and the proxy's page says why as its last error
+  until the proxy next reaches its remote. While a member the last index had cannot be
+  checked, that index is kept a minute longer, and the group then tries again.
+- **The index is written again when a member's changes**, behind the requests: a
+  machine is given the last one meanwhile, and waits only the first time. One index
+  of a directory is written at a time.
+- **The group's key** is made the first time it is needed, and is at
+  `/repository/<group>/megooarti-<group>.rsa.pub`, as a hosted repository's is.
 
 ## Clients
 
 Tested with apk on Alpine Linux 3.24 and 3.23 (apk-tools 3.0): a package built with
 `abuild`, uploaded and installed from a hosted repository; an index signed with a key
-apk was not given, refused; and a package from Alpine's mirror, installed through a
-proxy.
+apk was not given, refused; a package from Alpine's mirror, installed through a proxy;
+and both through a group, with the group's key the only one apk has, and a member
+signed by a key it was not given left out.
````

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/apk tests/test_documents.py -q`
Expected: 243 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests docs
git commit -m "feat: apk groups, one key for a directory of each member and for a directory they share"
```

---

### Task 4: apk through groups, on Alpine 3.24 and 3.23

**Files:**
- Modify: `backend/tests/test_apk_client.py`

**Interfaces:**
- Consumes: the stack built from the working tree, and plan 12e's fixtures of this module (`published`, `send`, `apk`, `call`).
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the tests**

Change `backend/tests/test_apk_client.py`:

```diff
@@ -213,3 +213,98 @@ def test_apk_installs_a_public_package_through_a_proxy_of_its_mirror(published,
 
     assert installed.returncode == 0, said(installed)
     assert installed.stdout.splitlines()[-1] == "42"
+
+
+# --- Groups ---------------------------------------------------------------------------
+
+ADMIN = "admin:'a brand new password'"  # what the `administrator` fixture made it
+# The guide's commands, as an administrator types them, against the stack: a proxy of
+# Alpine's mirror given Alpine's keys, as an Alpine machine has them.
+GUIDE = f"""
+set -e
+apk add -q jq curl > /dev/null
+keys=$(cat /etc/apk/keys/*.rsa.pub)
+jq -n --arg keys "$keys" '{{
+  name: "apk-alpine-keyed", format: "apk", type: "proxy",
+  proxy: {{remote_url: "{MIRROR}", auto_block: false}},
+  format_config: {{remote_keys: $keys}}
+}}' | curl -fsS -u {ADMIN} -H 'Content-Type: application/json' -d @- \\
+  http://gateway/api/v1/repositories > /dev/null
+echo made
+"""
+
+
+def made(administrator, body: dict) -> None:
+    status, _, answer = call("POST", "/repositories", body, administrator)
+    assert status == 201, answer
+
+
+@pytest.fixture(scope="module")
+def groups(published, administrator) -> Path:
+    """Two groups, with their keys saved beside the hosted repository's.
+
+    `apk-public`: the hosted repository and a proxy of Alpine's mirror given Alpine's
+    keys, merged in `v3.24/main/x86_64`. `apk-wrong`: the hosted repository, and a proxy
+    given a key Alpine does not sign with.
+    """
+    result = subprocess.run(
+        ["docker", "run", "--rm", "--network", NETWORK, IMAGES["3.24"], "sh", "-c", GUIDE],
+        capture_output=True,
+        text=True,
+        encoding="utf-8",
+        errors="replace",
+        timeout=900,
+        check=False,
+    )
+    assert result.stdout.strip().endswith("made"), said(result)
+    _, _, hosted_key = call("GET", f"/repositories/{HOSTED}/signing-key", headers=administrator)
+    made(
+        administrator,
+        {
+            "name": "apk-alpine-wrong",
+            "format": "apk",
+            "type": "proxy",
+            "proxy": {"remote_url": MIRROR, "auto_block": False},
+            # A key Alpine does not sign with: the hosted repository's own.
+            "format_config": {"remote_keys": hosted_key["public_key"]},
+        },
+    )
+    for name, members in (
+        ("apk-public", [HOSTED, "apk-alpine-keyed"]),
+        ("apk-wrong", [HOSTED, "apk-alpine-wrong"]),
+    ):
+        made(
+            administrator,
+            {"name": name, "format": "apk", "type": "group", "group": {"members": members}},
+        )
+        status, key = send("GET", f"{name}/megooarti-{name}.rsa.pub")
+        assert status == 200
+        (published / f"megooarti-{name}.rsa.pub").write_bytes(key)
+    return published
+
+
+@pytest.mark.parametrize("release", sorted(IMAGES))
+def test_apk_installs_ours_and_alpines_through_a_group_trusting_its_key_alone(groups, release):
+    installed = apk(
+        release,
+        groups,
+        # Alpine's own keys taken away: the group's is the only one.
+        "rm -f /etc/apk/keys/* && with_apk apk-public/v3.24/main /src/megooarti-apk-public.rsa.pub"
+        f" && apk add {PACKAGE} bc && {PACKAGE} && echo '6 * 7' | bc",
+    )
+
+    assert installed.returncode == 0, said(installed)
+    assert installed.stdout.splitlines()[-2:] == [f"hello from {PACKAGE} 1.0", "42"]
+
+
+def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_of_a_group(groups, administrator):
+    installed = apk(
+        "3.24",
+        groups,
+        "rm -f /etc/apk/keys/* && with_apk apk-wrong/v3.24/main /src/megooarti-apk-wrong.rsa.pub"
+        f" && apk add {PACKAGE} && {PACKAGE} && ! apk add bc",
+    )
+    _, _, shown = call("GET", "/repositories/apk-alpine-wrong", headers=administrator)
+
+    assert installed.returncode == 0, said(installed)
+    assert shown["status"]["last_error"].startswith("Left out of the group apk-wrong")
```

- [ ] **Step 2: Run them**

They need a Docker daemon and internet access: Alpine's mirror, and jq and curl from it for the guide's commands.

Run (in `backend/`): `uv run pytest -m docker tests/test_apk_client.py -v`
Expected: 9 passed, in about two minutes once the images are pulled. If a proxy's test fails because the mirror is slow or away, run it again before reading anything into it.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_apk_client.py
git commit -m "test: apk through groups, with the group's key the only one, and a member left out"
```

---

### Task 5: The spec, and everything once more

**Files:**
- Modify: `docs/superpowers/specs/2026-10-14-linux-package-formats-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the spec as this plan leaves it.

- [ ] **Step 1: Write what this plan settled into the spec**

Change `docs/superpowers/specs/2026-10-14-linux-package-formats-design.md`:

```diff
@@ -219,6 +219,17 @@ What the server derives from the packages, it does not store (as Maven's metadat
 | T11 | A `.PKGINFO` is read, and what is kept of it written out, in a worker thread. An index's RSA key is read when it first signs, in the worker thread that writes the indexes, and is not checked again as it was when kept. An imported key is read in a worker thread too, and may have at most 8192 bits. | Reading a 4096-bit key took a quarter of a second on the loop at every change, and a large imported key many seconds. |
 | T12 | The 16 MiB bound on a package's control part holds however the bytes arrive. | At an exact boundary of the pieces, the next piece was unpacked without a bound. |
 
+### Settled while building plan 12f
+
+| # | What | Why |
+| --- | --- | --- |
+| U1 | An apk proxy's `remote_keys` are RSA public keys, PEM, one or more one after the other, as `/etc/apk/keys/*.rsa.pub` holds them; anything else, or a private key, is refused with `422` at `format_config.remote_keys`. A proxy without them cannot be a member of a group (`422` at `group.members`), as an APT proxy cannot (Q5). | 4.5 and 7.4. |
+| U2 | A proxy member's index is checked as apk checks it: one of its `remote_keys` must have signed its second stream, with SHA-1 (`.SIGN.RSA.`) or SHA-256 (`.SIGN.RSA256.`). An index not signed, or signed in another way, is left out. | Alpine signs with SHA-1; abuild-sign can sign with either. |
+| U3 | A directory one member has is that member's index: its second stream, as the member wrote it, signed again with the group's key. | What apk reads is what the member's own signature vouched for. |
+| U4 | Where several members have a directory, the group writes an index of its own: the members' records as they wrote them, in their order, and of a name and version the first member's alone (in place of 7.4's "name, version and architecture": in one directory, a name and version is the one file apk asks for). Its `DESCRIPTION` is `MegooArti <group>`, and its files' times are 0, so that every process writes the same bytes but for the signature. | Packages are asked of the members in order: a later member's package of the same name and version could not be fetched through the group. |
+| U5 | A hosted member's directory without packages adds nothing where another member has the directory, as in a YUM group (S5); a group with a hosted member serves an empty index for a directory no member has packages in. | A machine can be set up before anything is uploaded. |
+| U6 | An apk group writes as YUM's do: behind the requests, one writing of a directory at a time (S10), the last whole index kept only while a member it had cannot be checked (S11), and why a member was left out said once the writing is done, and committed (S12). | The lessons of plans 12b and 12d. |
+
 ## 5. APT
 
 ### 5.1 Layout
```

- [ ] **Step 2: Run every suite**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3597 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; this plan changes nothing there.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, this plan's three new ones among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 12f settled"
```
