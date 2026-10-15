# YUM Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One group address, signed with one key of the group's own, serves the `repodata/` of its YUM members, your own packages and a distribution's mirror alike, after checking each member's metadata for the client.

**Architecture:** A group finds, for each directory a client asks for, the members that have a `repodata/` there: a hosted member in a directory as deep as its `repodata_depth` that holds packages, a proxy whose remote has `repodata/repomd.xml`. Every file the group reads of a member is checked against the checksum the member's `repomd.xml` names, and a proxy given its remote's keys (`remote_keys`) must have its `repomd.xml` signed by one of them. A directory one member has is that member's `repomd.xml`, signed again with the group's key, every other file sent on from that member. A directory several members have gets `primary.xml`, `filelists.xml` and `other.xml` merged by `<package>` element, an earlier member's package first, packed with zstd. What a group writes is kept in plan 12a's cache by a digest of its members' state, written behind the requests, as plan 12b's APT groups are; what such groups check of a member is moved into one module both use.

**Tech Stack:** Python 3.13, FastAPI, `pysequoia`, `zstandard`; pytest; `fedora:44` and `rockylinux/rockylinux:10` with dnf for the real-client tests.

**Spec:** [docs/superpowers/specs/2026-10-14-linux-package-formats-design.md](../specs/2026-10-14-linux-package-formats-design.md), sections 4.2, 4.4, 4.5, 6.4, 9, 10, 11 and the row of plan 12d in section 12, with what plans 12a to 12c settled (P1 to P12, Q1 to Q14, R1 to R12).

## Decisions this plan settles

Task 5 writes these into the spec's section 4, as "Settled while building plan 12d".

| # | Decision | Reason |
| --- | --- | --- |
| S1 | A directory one member of a group has is that member's: its `repomd.xml`, signed again with the group's key, and every file it names sent on from that member. Only a directory several members have gets metadata of the group's own. | dnf checks every file against the `repomd.xml` it was given, and a YUM `repomd.xml` says nothing of whose repository it is that could change under a client (unlike APT's `Release`, Q10). Writing Fedora's metadata again would cost seconds and memory for nothing. |
| S2 | A group merges its members' `primary.xml`, `filelists.xml` and `other.xml` by their `<package>` elements, copied as each member wrote them, without parsing a file whole, and packs what it writes with zstd. | Fedora 44's release and its updates: 1.3 GB of `filelists.xml`, merged in 17 seconds on the reference laptop with 245 MB at most in memory, 120 MB packed. Packed with gzip it would take most of a minute. dnf 5 on Fedora 44 and dnf 4 on Rocky Linux 10 read zstd (Task 4). |
| S3 | A merged directory's `repomd.xml` names the three files the group wrote, and of every other kind (package groups, updates, modules) the file of the first member that has it, as that member wrote its `<data>`. The members' `*.sqlite` and zchunk forms of the three are not named. Its revision and timestamps are the newest of its members' files' timestamps. | Spec 6.4. dnf reads the XML. Rocky's `repomd.xml` gives its release (`10.2`) as its revision, not a time; the newest timestamp makes the same bytes in any process. |
| S4 | Rocky Linux's mirrors sign their `repomd.xml` (`repomd.xml.asc`), Fedora's do not: the spec's 6.4 said neither does. A proxy given `remote_keys` must have a `repomd.xml.asc` that one of them made, or it is left out. | A group that skipped the check whenever the signature was missing would let whoever could change the mirror's answers skip it too. |
| S5 | A hosted member's directory that holds no packages adds nothing where another member has the directory. A group whose members have no packages in a directory serves that directory's empty metadata. | A hosted repository at depth 0 always has a `repodata/`: beside a mirror, it would turn the mirror's own into a merge for nothing. |
| S6 | What a group checks of a member, whatever the format, is in one module (`repositories/checks.py`): a proxy's `remote_keys` as a setting, leaving a member out, and the members as contexts of the writing's own session. APT's groups use it. `signing.verify_detached` checks a detached signature. | One way to leave a member out, and to say why. |
| S7 | Fedora 44 and Rocky Linux 10 have no modules: the spec's risk of a group that passes on one member's `modules` concerns older distributions only (Rocky Linux 8 and 9's AppStream). The guide says that modules are the first member's. | Fedora dropped modularity in Fedora 39, and RHEL 10 has none. |

**Changed after the whole-branch review.** The task bodies below show the code as the tasks made it. The branch differs from them as follows; each change was made test-first where code changed, and the spec's section 4 records what they settle as S8 to S14.

| # | Change | Reason |
| --- | --- | --- |
| F1 | `docs/formats/yum.md`: with a member without `remote_keys`, machines check every package (`gpgcheck=1`); the example signs its packages, and reaches Rocky over HTTPS. `test_yum_client.py`: the mirrors over HTTPS, our package signed with `rpmsign`, and `gpgcheck=1` through the merging groups (`with_dnf` takes several keys). | C1: the guide's `gpgcheck=0` let a group vouch for whatever a keyless mirror's network path served. |
| F2 | `groups.Stale`; `proxy.ensure_cached(..., again=True)`; `groups._write` asks stale proxies again (`_ask_again`) once, and writes for what it then finds (`_digest`). | C2, I7. |
| F3 | `derived.written(..., stale=True)` begins no writing of a directory or suite while another runs (`derived._behind`). | I3. |
| F4 | `derived.Written.members`; `groups._write` keeps the last whole metadata only while a member it was written from is left out, in the offers or in the merge (`_Outcome`). | I6. |
| F5 | `groups._merged_kind`: a member whose `filelists.xml` or `other.xml` cannot be read is left out of that file alone. `_leave` notes; `_write` says, at the end; `checks.leave_out` commits. | I5, I8. |
| F6 | `merge._pieces`: several streams in one file, and a file that ends inside one refused. | Minor 1, re-graded: a member's file answered `500` for the whole group. |
| F7 | In the tests, `metadata()` waits for what is written behind each request, as plan 12b's did. | The tests of F2. |

## Global Constraints

- **A client trusts the group's key and nothing else**: nothing a member gave is named in the group's `repomd.xml` unless it was checked against the checksum the member's `repomd.xml` names, and a proxy given `remote_keys` is used only if they signed its `repomd.xml`.
- **What is read of a member is bounded** (spec 9): a `repomd.xml` and its signature at 16 MiB, a packed file at 256 MiB, unpacked at 1 GiB.
- **A format never touches a table or a file**: a group works through its members' contexts, `proxy.ensure_cached`, and `checks.leave_out`.
- **Every test of a stack is marked `docker`.** The guide's commands for a proxy given its remote's keys are run by one, against the stack.
- **A table's line under its headings is `| --- | --- |`.** Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **A proxy member that changes between the group's `repomd.xml` and a client's next request**: a mirror updated, `repomd.xml` and `repomd.xml.asc` fetched at different moments, a hash-named file a pass-through `repomd.xml` named that the mirror has since removed.
2. **Large members**: Fedora's release and updates in one directory, two such directories, the group's budget of 256 MiB in the cache, several merges at once, and requests that wait for one another.
3. **What a group signs that it did not check**: a pass-through directory of a proxy without `remote_keys`, a file of another kind named from the first member that has it (comps, updateinfo), a `<location xml:base=...>` in a member's `primary.xml`.
4. **Members' metadata that is unusual**: `primary.xml` whose elements have other attribute orders or namespaces, packed in a way not tried (`.bz2` from a real mirror), a member whose `filelists.xml` or `other.xml` is missing or fails its check while its `primary.xml` passes.
5. **The members' order and depth**: hosted members of different `repodata_depth`, a group within a group, a member taken out of the group while its metadata is kept.

---

### Task 1: What a group checks of its members, in one place

**Files:**
- Create: `backend/src/megooarti/repositories/checks.py`
- Modify: `backend/src/megooarti/repositories/signing.py`, `backend/src/megooarti/repositories/apt/format.py`, `backend/src/megooarti/repositories/apt/groups.py`
- Modify (tests): `backend/tests/repositories/test_signing.py`; create in `backend/tests/repositories/yum/data/`: `rocky.sh`, and what it fetches: Rocky Linux 10's BaseOS `repomd.xml`, its `repomd.xml.asc`, and `RPM-GPG-KEY-Rocky-10`

**Interfaces:**
- Consumes: plan 12b's `signing.read_public_keys`, `signing.Unverified`, `proxy_state.record_failure`, `build_context`.
- Produces: `signing.verify_detached(data, signature, certificates) -> None` (raises `Unverified`); `checks.LeftOut`, `checks.remote_keys(member) -> str`, `checks.remote_keys_setting(config, format_label) -> dict` (raises a 422 at `format_config.*`), `async checks.leave_out(context, member, reason)`, `async checks.members_in(db, context, ids) -> list[RepositoryContext]`. APT's groups and proxies use them in place of their own.

- [ ] **Step 1: Write the failing tests**

The three Rocky files are Rocky Linux's own, as `data/rocky.sh` fetched them on 15 October 2026: copy them from the scratch clone the plan was built in (`%TEMP%/claude/c--Projects-MegooArti/bc22c7c6-1db8-4e66-8027-be400481b47b/scratchpad/plan12d/wt/backend/tests/repositories/yum/data/`), or fetch them again with `rocky.sh` (run in that directory; the signature is then of the newer `repomd.xml`, and Task 2's test of its revision and timestamp says the newer ones).

Change `backend/tests/repositories/test_signing.py`:

```diff
@@ -12,6 +12,7 @@ from megooarti.secrets_box import forget_keys
 from megooarti.security import roles
 from tests.accounts import PASSWORD, basic, error_code
 from tests.repositories.apt.packages import DATA
+from tests.repositories.yum.packages import DATA as YUM_DATA
 
 KEYS = "/api/v1/repositories/files/signing-key"
 
@@ -295,3 +296,28 @@ def test_a_clear_signed_message_none_of_the_keys_signed_is_refused():
         signing.verify_clear(altered, debian)
     with pytest.raises(signing.Unverified):
         signing.verify_clear(b"Origin: Debian\n", debian)
+
+
+def test_a_detached_signature_one_of_the_keys_made_is_taken():
+    keys = signing.read_public_keys((YUM_DATA / "RPM-GPG-KEY-Rocky-10").read_text(encoding="utf-8"))
+    repomd = (YUM_DATA / "rocky-10-baseos-repomd.xml").read_bytes()
+
+    signing.verify_detached(
+        repomd, (YUM_DATA / "rocky-10-baseos-repomd.xml.asc").read_bytes(), keys
+    )
+
+
+def test_a_detached_signature_none_of_the_keys_made_is_refused():
+    rocky = signing.read_public_keys(
+        (YUM_DATA / "RPM-GPG-KEY-Rocky-10").read_text(encoding="utf-8")
+    )
+    other = signing.read_public_keys(signing.generate_openpgp("Someone else").public_key)
+    repomd = (YUM_DATA / "rocky-10-baseos-repomd.xml").read_bytes()
+    signature = (YUM_DATA / "rocky-10-baseos-repomd.xml.asc").read_bytes()
+
+    with pytest.raises(signing.Unverified):
+        signing.verify_detached(repomd, signature, other)
+    with pytest.raises(signing.Unverified):
+        signing.verify_detached(repomd.replace(b"primary", b"primarx"), signature, rocky)
+    with pytest.raises(signing.Unverified):
+        signing.verify_detached(repomd, b"not a signature", rocky)
```
Create `backend/tests/repositories/yum/data/rocky.sh`:

```sh
# Rocky Linux 10's BaseOS: its repomd.xml as signed, and the key it is signed with.
U=http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os/repodata
curl -sf $U/repomd.xml -o rocky-10-baseos-repomd.xml
curl -sf $U/repomd.xml.asc -o rocky-10-baseos-repomd.xml.asc
docker run --rm rockylinux/rockylinux:10 cat /etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10 > RPM-GPG-KEY-Rocky-10
```

Copy, from the scratch clone: `rocky-10-baseos-repomd.xml`, `rocky-10-baseos-repomd.xml.asc`, `RPM-GPG-KEY-Rocky-10`.

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_signing.py -q`
Expected: 2 failed, 25 passed: `signing` has no `verify_detached`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/signing.py`:

```diff
@@ -149,6 +149,23 @@ def verify_clear(signed: bytes, certificates: list[object]) -> bytes:
         raise Unverified(str(error).splitlines()[0]) from None
 
 
+def verify_detached(data: bytes, signature: bytes, certificates: list[object]) -> None:
+    """Raise Unverified unless one of the keys made this signature of `data`.
+
+    A detached signature, as a remote's `repomd.xml.asc` is.
+    """
+    try:
+        pysequoia.verify(
+            bytes=data,
+            store=lambda _: certificates,
+            signature=pysequoia.Sig.from_bytes(signature),
+        )
+    except (RuntimeError, ValueError) as error:
+        raise Unverified(
+            str(error).splitlines()[0] if str(error) else "it is not a signature"
+        ) from None
+
+
 def signs(repository: Repository) -> str | None:
     """The kind of key this repository signs with, or None if it signs nothing.
 
```

Create `backend/src/megooarti/repositories/checks.py`:

```python
"""What a group that signs what it serves checks of its members, whatever their format.

A client of such a group trusts the group's key and nothing else, so the group checks
what a proxy member's remote signed with the keys the remote was given (`remote_keys`).
A member that fails a check is left out: the reason is logged, and kept as the proxy's
last error until it next reaches its remote.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy_state, signing
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Repository

log = structlog.get_logger(__name__)


class LeftOut(Exception):
    """A member that a check found wanting, and why."""


def remote_keys(member: RepositoryContext) -> str:
    """A proxy's remote's public keys, armoured, or nothing."""
    return member.repository.config.get("format_config", {}).get("remote_keys") or ""


def remote_keys_setting(config: dict[str, Any], format_label: str) -> dict[str, Any]:
    """A proxy's settings: its remote's public keys, which a group checks it with."""

    def invalid(field: str, message: str) -> ApiError:
        details = [{"field": field, "message": message}]
        return ApiError(422, "validation_error", "The request is not valid.", details)

    unknown = sorted(set(config) - {"remote_keys"})
    if unknown:
        raise invalid(f"format_config.{unknown[0]}", f"This is not a setting of {format_label}.")
    keys = config.get("remote_keys") or ""
    if not isinstance(keys, str):
        raise invalid("format_config.remote_keys", "The keys are armoured text.")
    if not keys.strip():
        return {}
    try:
        signing.read_public_keys(keys)
    except signing.KeysUnusable as error:
        raise invalid("format_config.remote_keys", str(error)) from None
    return {"remote_keys": keys}


async def leave_out(context: RepositoryContext, member: RepositoryContext, reason: str) -> None:
    """Say that a group left a member out, and why. The caller commits."""
    log.warning(
        "group_member_unverified",
        group=context.repository.name,
        member=member.repository.name,
        reason=reason,
    )
    if member.repository.type == "proxy":
        said = f"Left out of the group {context.repository.name}: {reason}"
        await proxy_state.record_failure(
            member.db, member.repository, utcnow(), said, blockable=False
        )


async def members_in(
    db: AsyncSession, context: RepositoryContext, ids: Sequence[uuid.UUID]
) -> list[RepositoryContext]:
    """A group's members, by their ids, as contexts on a session of the caller's."""
    return [
        await build_context(
            db,
            context.settings,
            await db.get(Repository, member_id),
            context.principal,
            outbound=context.outbound,
        )
        for member_id in ids
    ]
```

Change `backend/src/megooarti/repositories/apt/format.py`:

```diff
@@ -24,7 +24,7 @@ from starlette.requests import Request
 from starlette.responses import Response
 
 from megooarti.errors import ApiError
-from megooarti.repositories import derived, signing
+from megooarti.repositories import checks, derived, signing
 from megooarti.repositories.apt import control, debs, indexes, paths, versions
 from megooarti.repositories.content import RepositoryContext, Snapshot
 from megooarti.repositories.formats import (
@@ -252,23 +252,6 @@ async def _public_key(context: RepositoryContext, request: Request) -> Response:
     )
 
 
-def _remote_keys(config: dict[str, Any]) -> dict[str, Any]:
-    """A proxy's settings: its remote's public keys, which a group checks it with."""
-    unknown = sorted(set(config) - {"remote_keys"})
-    if unknown:
-        raise _invalid_setting(f"format_config.{unknown[0]}", "This is not a setting of APT.")
-    keys = config.get("remote_keys") or ""
-    if not isinstance(keys, str):
-        raise _invalid_setting("format_config.remote_keys", "The keys are armoured text.")
-    if not keys.strip():
-        return {}
-    try:
-        signing.read_public_keys(keys)
-    except signing.KeysUnusable as error:
-        raise _invalid_setting("format_config.remote_keys", str(error)) from None
-    return {"remote_keys": keys}
-
-
 class AptFormat(Format):
     name = "apt"
     types = frozenset({"hosted", "proxy", "group"})
@@ -280,7 +263,7 @@ class AptFormat(Format):
     ) -> dict[str, Any]:
         """A hosted repository's suite, which never changes; a proxy's remote's keys."""
         if repository_type == "proxy":
-            return _remote_keys(config)
+            return checks.remote_keys_setting(config, "APT")
         if repository_type != "hosted":
             return super().validate_config(repository_type, config, current)
         unknown = sorted(set(config) - {"suite"})
```

Change `backend/src/megooarti/repositories/apt/groups.py`:

```diff
@@ -33,21 +33,19 @@ from collections.abc import Sequence
 from dataclasses import dataclass, replace
 from datetime import datetime, timedelta
 
-import structlog
 from sqlalchemy.ext.asyncio import AsyncSession
 from starlette.requests import Request
 from starlette.responses import Response
 
 from megooarti.clock import utcnow
 from megooarti.errors import ApiError
-from megooarti.repositories import derived, group, proxy, proxy_state, signing
+from megooarti.repositories import derived, group, proxy, signing
 from megooarti.repositories.apt import format as apt
 from megooarti.repositories.apt import merge, releases
-from megooarti.repositories.content import RepositoryContext, TooLarge, build_context
+from megooarti.repositories.checks import LeftOut, leave_out, members_in, remote_keys
+from megooarti.repositories.content import RepositoryContext, TooLarge
 from megooarti.repositories.formats import Serve
-from megooarti.repositories.models import Repository, SigningKey
-
-log = structlog.get_logger(__name__)
+from megooarti.repositories.models import SigningKey
 
 # The most of a member's `InRelease`, and of a packed `Packages` file, that is read.
 RELEASE_MOST = 16 * 1024 * 1024
@@ -61,10 +59,6 @@ _SIGNED = ("Release", "InRelease", "Release.gpg")
 _INCOMPLETE = "~"
 
 
-class LeftOut(Exception):
-    """A member that a check found wanting, and why."""
-
-
 @dataclass(frozen=True)
 class Offer:
     """What one member has of a suite."""
@@ -78,10 +72,6 @@ def _not_found(message: str) -> ApiError:
     return ApiError(404, "not_found", message)
 
 
-def remote_keys(member: RepositoryContext) -> str:
-    return member.repository.config.get("format_config", {}).get("remote_keys") or ""
-
-
 async def _token(member: RepositoryContext, suite: str) -> str | None:
     """What a member's indexes of a suite are now, or None if it does not have the suite."""
     if member.repository.type == "hosted":
@@ -103,20 +93,6 @@ async def _token(member: RepositoryContext, suite: str) -> str | None:
     return f"{member.repository.id}:{stored.sha256}:{keys}"
 
 
-async def _leave_out(context: RepositoryContext, member: RepositoryContext, reason: str) -> None:
-    log.warning(
-        "group_member_unverified",
-        group=context.repository.name,
-        member=member.repository.name,
-        reason=reason,
-    )
-    if member.repository.type == "proxy":
-        said = f"Left out of the group {context.repository.name}: {reason}"
-        await proxy_state.record_failure(
-            member.db, member.repository, utcnow(), said, blockable=False
-        )
-
-
 async def _offer(member: RepositoryContext, suite: str, now: datetime) -> Offer:
     """What a member has of a suite, checked. Raises LeftOut."""
     if member.repository.type == "hosted":
@@ -243,7 +219,7 @@ async def _merged(
                         texts.append(await _packages(offer, suite, directory))
                     except LeftOut as error:
                         incomplete = True
-                        await _leave_out(context, offer.member, str(error))
+                        await leave_out(context, offer.member, str(error))
                 packed, named = await asyncio.to_thread(_packed, texts)
                 files[f"{directory}/Packages.gz"] = packed
                 entries[f"{directory}/Packages.gz"] = releases.Entry(
@@ -308,23 +284,14 @@ async def _write(
     """What the group has of a suite, written with a session of its own."""
     of = (context.repository.id, suite)
     now = utcnow()
-    members = [
-        await build_context(
-            db,
-            context.settings,
-            await db.get(Repository, member_id),
-            context.principal,
-            outbound=context.outbound,
-        )
-        for member_id in candidates
-    ]
+    members = await members_in(db, context, candidates)
     offers, left_out = [], False
     for member in members:
         try:
             offers.append(await _offer(member, suite, now))
         except LeftOut as error:
             left_out = True
-            await _leave_out(context, member, str(error))
+            await leave_out(context, member, str(error))
     previous = derived.peek(of)
     whole = previous is not None and not str(previous.revision).endswith(_INCOMPLETE)
     if left_out and whole:
```

- [ ] **Step 4: Run the tests to verify they pass**

APT's groups now use the shared checks: their tests are run as well, unchanged.

Run (in `backend/`): `uv run pytest tests/repositories/test_signing.py tests/repositories/apt -q`
Expected: 227 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "refactor: what a group checks of its members, in one module; check a detached signature"
```

---

### Task 2: Merging members' `repodata/`

**Files:**
- Create: `backend/src/megooarti/repositories/yum/merge.py`, `backend/tests/repositories/yum/test_merge.py`

**Interfaces:**
- Consumes: Task 1's Rocky files; plan 12c's `createrepo-*.xml`, `real-createrepo-*.xml`, `empty-createrepo-*.xml` in `data/`.
- Produces: `merge.UNPACKED_MOST`, `merge.KINDS`, `merge.InvalidMetadata` (its second argument, where given, is the index of the member at fault), `merge.Data(type, href, checksum_type, checksum, element)`, `merge.Repomd(revision, moment, data)`, `merge.parse_repomd(text) -> Repomd`, `merge.check(data, packed)`, `merge.unpacked(href, packed, most=...) -> Iterator[bytes]`, `merge.packages(pieces) -> Iterator[bytes]`, `merge.kept(primaries) -> list[set[bytes]]`, `merge.Merged(kind, packed, open_checksum, open_size)` with `.name`, `merge.merged(kind, members, kept) -> Merged`, `merge.repomd(revision, parts, passed) -> bytes`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/repositories/yum/test_merge.py`:

```python
"""Merging members' `repodata/`: by `<package>` element, an earlier member's first."""

import bz2
import gzip
import hashlib
import lzma
import re
from xml.etree import ElementTree

import pytest
import zstandard

from megooarti.repositories.yum import merge
from tests.repositories.yum.packages import DATA

REPO = "{http://linux.duke.edu/metadata/repo}"
COMMON = "{http://linux.duke.edu/metadata/common}"
PACKERS = {
    "gz": lambda data: gzip.compress(data, mtime=0),
    "xz": lzma.compress,
    "zst": zstandard.ZstdCompressor().compress,
    "bz2": bz2.compress,
}


def text(name: str) -> bytes:
    return (DATA / name).read_bytes()


def packed(name: str, kind: str = "gz") -> tuple[str, bytes]:
    """A file createrepo_c wrote, packed as a member could have it, with its name."""
    return f"repodata/x-{name}.{kind}", PACKERS[kind](text(name))


def unpacked(merged: merge.Merged) -> bytes:
    return zstandard.ZstdDecompressor().decompressobj().decompress(merged.packed)


def element(name: str, version: str = "1.0", pkgid: str = "a" * 64, href: str = "") -> bytes:
    """A package of a `primary.xml`, as createrepo_c writes one, cut to what is read."""
    return (
        f'<package type="rpm">\n  <name>{name}</name>\n  <arch>noarch</arch>\n'
        f'  <version epoch="0" ver="{version}" rel="1"/>\n'
        f'  <checksum type="sha256" pkgid="YES">{pkgid}</checksum>\n'
        f'  <location href="{href or name + ".rpm"}"/>\n</package>'
    ).encode()


def primary(*elements: bytes) -> tuple[str, bytes]:
    head = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n<metadata xmlns="http://linux.duke.edu/'
        b'metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="9">\n'
    )
    return "repodata/p-primary.xml.gz", gzip.compress(
        head + b"\n".join(elements) + b"\n</metadata>", mtime=0
    )


def test_a_repomd_says_each_file_it_names_and_its_checksum():
    said = merge.parse_repomd(text("rocky-10-baseos-repomd.xml"))

    assert list(said.data)[:3] == ["primary", "filelists", "other"]
    assert {"group", "group_xz", "updateinfo", "primary_db"} <= set(said.data)
    primary_data = said.data["primary"]
    assert primary_data.href.startswith("repodata/") and primary_data.href.endswith(
        "-primary.xml.gz"
    )
    assert (primary_data.checksum_type, len(primary_data.checksum)) == ("sha256", 64)
    assert primary_data.element.startswith(b'<data type="primary">')
    assert primary_data.element.endswith(b"</data>")
    assert said.revision == "10.2"  # Rocky says its release, not a time
    assert said.moment == 1791964571  # the newest of its files


@pytest.mark.parametrize(
    "text",
    [
        b"not xml",
        b"<other/>",
        b'<repomd xmlns="http://linux.duke.edu/metadata/repo"><data type="primary"/></repomd>',
    ],
)
def test_what_is_not_a_repomd_that_can_be_read_is_refused(text):
    with pytest.raises(merge.InvalidMetadata):
        merge.parse_repomd(text)


def test_a_file_is_checked_against_the_checksum_its_repomd_names():
    data = merge.Data(
        "primary", "repodata/p.xml.gz", "sha256", hashlib.sha256(b"x").hexdigest(), b""
    )

    merge.check(data, b"x")
    with pytest.raises(merge.InvalidMetadata, match="not the one its repomd.xml names"):
        merge.check(data, b"y")
    with pytest.raises(merge.InvalidMetadata, match="unknown kind"):
        merge.check(merge.Data("primary", "p", "md5", "x", b""), b"x")


@pytest.mark.parametrize("kind", sorted(PACKERS))
def test_a_file_is_unpacked_however_it_was_packed(kind):
    href, data = packed("createrepo-primary.xml", kind)

    assert b"".join(merge.unpacked(href, data)) == text("createrepo-primary.xml")


def test_a_file_larger_unpacked_than_the_bound_or_broken_is_refused():
    href, data = packed("createrepo-filelists.xml")

    with pytest.raises(merge.InvalidMetadata, match="larger than"):
        list(merge.unpacked(href, data, most=100))
    with pytest.raises(merge.InvalidMetadata, match="cannot be unpacked"):
        list(merge.unpacked(href, data[:20] + b"\xff" * 50))
    with pytest.raises(merge.InvalidMetadata, match="packed in a way"):
        list(merge.unpacked("repodata/x-primary.xml.lz4", data))


def test_package_elements_are_found_whatever_pieces_the_text_comes_in():
    whole = text("real-createrepo-primary.xml")
    expected = re.findall(rb"<package .*?</package>", whole, re.DOTALL)

    for size in (1, 7, 100, len(whole)):
        pieces = [whole[at : at + size] for at in range(0, len(whole), size)]
        assert list(merge.packages(pieces)) == expected


@pytest.mark.parametrize("kind", merge.KINDS)
@pytest.mark.parametrize("prefix", ["createrepo", "real-createrepo", "empty-createrepo"])
def test_one_members_files_merged_alone_are_what_createrepo_c_wrote(prefix, kind):
    members = [packed(f"{prefix}-{kind}.xml")]
    kept = merge.kept([packed(f"{prefix}-primary.xml")])

    merged = merge.merged(kind, members, kept)

    assert unpacked(merged) == text(f"{prefix}-{kind}.xml")
    assert merged.open_checksum == hashlib.sha256(text(f"{prefix}-{kind}.xml")).hexdigest()
    assert merged.open_size == len(text(f"{prefix}-{kind}.xml"))
    assert merged.name == f"{hashlib.sha256(merged.packed).hexdigest()}-{kind}.xml.zst"


def test_two_members_files_are_merged_the_earlier_first():
    kept = merge.kept([packed("real-createrepo-primary.xml"), packed("createrepo-primary.xml")])

    merged = {
        kind: unpacked(
            merge.merged(
                kind,
                [packed(f"real-createrepo-{kind}.xml"), packed(f"createrepo-{kind}.xml")],
                kept,
            )
        )
        for kind in merge.KINDS
    }

    names = [p.findtext(f"{COMMON}name") for p in ElementTree.fromstring(merged["primary"])]
    assert names == ["bash", "setup", "megooarti-hello", "megooarti-tool"]
    assert b'packages="4"' in merged["primary"]
    for kind in ("filelists", "other"):
        tree = ElementTree.fromstring(merged[kind])
        assert [package.get("name") for package in tree] == names


def test_a_package_an_earlier_member_has_is_left_out_of_a_later_ones():
    first = primary(element("hello", pkgid="1" * 64), element("tool", pkgid="2" * 64))
    later = primary(
        element("hello", pkgid="3" * 64, href="other/hello.rpm"),  # the same package
        element("hello", "2.0", pkgid="4" * 64, href="hello-2.rpm"),  # another version
        element("other", pkgid="5" * 64, href="tool.rpm"),  # at the earlier's tool's path
        element("again", pkgid="6" * 64),
        element("again", pkgid="6" * 64),  # twice in one member
    )

    assert merge.kept([first, later]) == [{b"1" * 64, b"2" * 64}, {b"4" * 64, b"6" * 64}]


def test_a_member_whose_primary_cannot_be_read_is_named():
    broken = primary(b'<package type="rpm"><name>x</name></package>')

    with pytest.raises(merge.InvalidMetadata) as raised:
        merge.kept([primary(element("hello")), broken])

    assert raised.value.args[1] == 1


def test_the_groups_repomd_names_what_it_wrote_and_what_it_passes_on():
    kept = merge.kept([packed("createrepo-primary.xml")])
    parts = [merge.merged(kind, [packed(f"createrepo-{kind}.xml")], kept) for kind in merge.KINDS]
    comps = merge.parse_repomd(text("rocky-10-baseos-repomd.xml")).data["group"]

    written = merge.repomd("1792005637", parts, [comps])

    tree = ElementTree.fromstring(written)
    assert tree.findtext(f"{REPO}revision") == "1792005637"
    data = {node.get("type"): node for node in tree.iter(f"{REPO}data")}
    assert list(data) == ["primary", "filelists", "other", "group"]
    for part in parts:
        node = data[part.kind]
        assert node.find(f"{REPO}location").get("href") == f"repodata/{part.name}"
        assert node.findtext(f"{REPO}checksum") == hashlib.sha256(part.packed).hexdigest()
        assert node.findtext(f"{REPO}open-checksum") == part.open_checksum
        assert node.findtext(f"{REPO}size") == str(len(part.packed))
    assert comps.element in written
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/yum/test_merge.py -q`
Expected: 1 error during collection: `megooarti.repositories.yum` has no `merge`.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/repositories/yum/merge.py`:

```python
"""Members' `repodata/` merged into one: what a group of YUM repositories serves.

Each member's `primary.xml`, `filelists.xml` and `other.xml` is a list of packages,
each in a `<package>` element of its own. They are merged by those elements, copied
as the member wrote them, without being parsed as a whole: Fedora's `filelists.xml`
is 800 MB of text, read as it is unpacked and written as it is packed. A package (the
same name, epoch, version, release and architecture) that an earlier member has is
left out of a later one's, and so is a later member's package at a path an earlier
member holds with other content: the group could not give a client that file.
"""

import bz2
import hashlib
import io
import lzma
import re
import zlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from xml.etree import ElementTree

import zstandard

# The most of one of a member's files that is unpacked (spec 9).
UNPACKED_MOST = 1024 * 1024 * 1024
KINDS = ("primary", "filelists", "other")
_PIECE = 1024 * 1024
_REPO = "{http://linux.duke.edu/metadata/repo}"
_START = b'<?xml version="1.0" encoding="UTF-8"?>\n'
_HEADS = {
    "primary": b'<metadata xmlns="http://linux.duke.edu/metadata/common" '
    b'xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="%d">\n',
    "filelists": b'<filelists xmlns="http://linux.duke.edu/metadata/filelists" packages="%d">\n',
    "other": b'<otherdata xmlns="http://linux.duke.edu/metadata/other" packages="%d">\n',
}
_ENDS = {"primary": b"</metadata>", "filelists": b"</filelists>", "other": b"</otherdata>"}
_OPEN, _CLOSE = b"<package ", b"</package>"
_DATA = re.compile(rb'<data type="([^"]+)">.*?</data>', re.DOTALL)
_NAME = re.compile(rb"<name>([^<]*)</name>")
_ARCH = re.compile(rb"<arch>([^<]*)</arch>")
_VERSION = re.compile(rb'<version epoch="([^"]*)" ver="([^"]*)" rel="([^"]*)"/>')
_PKGID = re.compile(rb'<checksum type="[^"]*" pkgid="YES">([^<]*)</checksum>')
_LOCATION = re.compile(rb"<location ([^>]*)/>")
_OWNED = re.compile(rb'<package pkgid="([^"]*)"')
_ALGORITHMS = {"sha": "sha1", "sha1": "sha1", "sha224": "sha224", "sha256": "sha256"}
_ALGORITHMS |= {"sha384": "sha384", "sha512": "sha512"}


class InvalidMetadata(ValueError):
    """A member's metadata that the group cannot read, or that is not what it says."""


@dataclass(frozen=True)
class Data:
    """One file a `repomd.xml` names."""

    type: str
    href: str  # under the directory of `repodata/`
    checksum_type: str
    checksum: str
    element: bytes  # the `<data>` element as the member wrote it


@dataclass(frozen=True)
class Repomd:
    revision: str  # a time, or whatever its writer chose (Rocky says its release)
    moment: int  # the newest of its files' timestamps, 0 if it says none
    data: dict[str, Data]  # by type, in the member's order


def parse_repomd(text: bytes) -> Repomd:
    """What a `repomd.xml` names. Raises InvalidMetadata."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise InvalidMetadata(f"its repomd.xml cannot be read: {error}") from None
    if root.tag != f"{_REPO}repomd":
        raise InvalidMetadata("its repomd.xml is not one")
    elements = {found[1].decode(): found[0] for found in _DATA.finditer(text)}
    data, moments = {}, [0]
    for node in root.iter(f"{_REPO}data"):
        kind = node.get("type", "")
        checksum = node.find(f"{_REPO}checksum")
        location = node.find(f"{_REPO}location")
        if checksum is None or location is None or kind not in elements:
            raise InvalidMetadata(f"its repomd.xml names {kind or 'a file'} without its checksum")
        data[kind] = Data(
            kind,
            location.get("href", ""),
            checksum.get("type", ""),
            (checksum.text or "").strip(),
            elements[kind],
        )
        stamp = (node.findtext(f"{_REPO}timestamp") or "").strip()
        moments.append(int(stamp) if stamp.isascii() and stamp.isdigit() else 0)
    return Repomd((root.findtext(f"{_REPO}revision") or "").strip(), max(moments), data)


def check(data: Data, packed: bytes) -> None:
    """Raise InvalidMetadata unless a file is the one `repomd.xml` names."""
    algorithm = _ALGORITHMS.get(data.checksum_type)
    if algorithm is None:
        raise InvalidMetadata(f"its {data.type} has a checksum of an unknown kind")
    if hashlib.new(algorithm, packed).hexdigest() != data.checksum.lower():
        raise InvalidMetadata(f"its {data.type} is not the one its repomd.xml names")


def _decompressor(href: str):
    if href.endswith(".gz"):
        return zlib.decompressobj(wbits=47).decompress
    if href.endswith(".xz"):
        return lzma.LZMADecompressor().decompress
    if href.endswith(".bz2"):
        return bz2.BZ2Decompressor().decompress
    if href.endswith(".zst"):
        return zstandard.ZstdDecompressor().decompressobj().decompress
    if href.endswith(".xml"):
        return lambda piece: piece
    raise InvalidMetadata(f"{href.rpartition('/')[2]} is packed in a way this server cannot read")


def unpacked(href: str, packed: bytes, most: int = UNPACKED_MOST) -> Iterator[bytes]:
    """A packed file's text, in pieces. Raises InvalidMetadata beyond `most` bytes."""
    unpack = _decompressor(href)
    total = 0
    for at in range(0, len(packed), _PIECE // 16):
        try:
            piece = unpack(packed[at : at + _PIECE // 16])
        except (zlib.error, lzma.LZMAError, OSError, zstandard.ZstdError, ValueError) as error:
            raise InvalidMetadata(
                f"{href.rpartition('/')[2]} cannot be unpacked: {error}"
            ) from None
        total += len(piece)
        if total > most:
            raise InvalidMetadata(f"{href.rpartition('/')[2]} is larger than this server reads")
        if piece:
            yield piece


def packages(pieces: Iterable[bytes]) -> Iterator[bytes]:
    """Each `<package>` element of a text, as it was written."""
    held = b""
    for piece in pieces:
        held += piece
        at = 0
        while True:
            start = held.find(_OPEN, at)
            if start < 0:
                at = max(at, len(held) - len(_OPEN))
                break
            end = held.find(_CLOSE, start)
            if end < 0:
                at = start
                break
            at = end + len(_CLOSE)
            yield held[start:at]
        held = held[at:]


def _identity(element: bytes) -> tuple[tuple[bytes, ...], bytes, bytes]:
    """A package's name, epoch, version, release and architecture; its id; its path."""
    name, arch = _NAME.search(element), _ARCH.search(element)
    version, pkgid = _VERSION.search(element), _PKGID.search(element)
    location = _LOCATION.search(element)
    if not (name and arch and version and pkgid and location):
        raise InvalidMetadata("a package of its primary.xml cannot be read")
    nevra = (name[1], *version.groups(), arch[1])
    return nevra, pkgid[1], location[1]


def _id_of(kind: str, element: bytes) -> bytes:
    """A package's id: its checksum, which `filelists.xml` and `other.xml` call `pkgid`."""
    if kind == "primary":
        return _identity(element)[1]
    found = _OWNED.search(element)
    if found is None:
        raise InvalidMetadata(f"a package of its {kind}.xml cannot be read")
    return found[1]


def kept(primaries: Sequence[tuple[str, bytes]]) -> list[set[bytes]]:
    """Which packages of each member's `primary.xml` the group lists, by their ids.

    `primaries` are each member's, packed, with the name it has. Raises InvalidMetadata,
    with the member's index as its second argument.
    """
    seen: set[tuple[bytes, ...]] = set()
    held: dict[bytes, bytes] = {}  # by path, the id of what an earlier member has there
    found: list[set[bytes]] = []
    for number, (href, packed) in enumerate(primaries):
        mine: set[bytes] = set()
        try:
            for element in packages(unpacked(href, packed)):
                nevra, pkgid, location = _identity(element)
                if nevra in seen or held.get(location, pkgid) != pkgid:
                    continue
                seen.add(nevra)
                held.setdefault(location, pkgid)
                mine.add(pkgid)
        except InvalidMetadata as error:
            raise InvalidMetadata(str(error), number) from None
        found.append(mine)
    return found


@dataclass(frozen=True)
class Merged:
    """One merged file: packed, and what `repomd.xml` says of it."""

    kind: str
    packed: bytes
    open_checksum: str
    open_size: int

    @property
    def name(self) -> str:
        return f"{hashlib.sha256(self.packed).hexdigest()}-{self.kind}.xml.zst"


def merged(kind: str, members: Sequence[tuple[str, bytes]], kept: Sequence[set[bytes]]) -> Merged:
    """Members' files of one kind, merged: each member's packages that `kept` keeps.

    Packed with zstd, which takes seconds for Fedora's whole `filelists.xml` where gzip
    would take most of a minute.
    """
    sink = io.BytesIO()
    opened = hashlib.sha256()
    size = 0
    with zstandard.ZstdCompressor(level=3).stream_writer(sink, closefd=False) as packer:

        def write(text: bytes) -> None:
            nonlocal size
            opened.update(text)
            size += len(text)
            packer.write(text)

        write(_START + _HEADS[kind] % sum(len(mine) for mine in kept))
        for number, (href, packed) in enumerate(members):
            wanted, written = kept[number], set()
            try:
                for element in packages(unpacked(href, packed)):
                    pkgid = _id_of(kind, element)
                    if pkgid in wanted and pkgid not in written:
                        written.add(pkgid)
                        write(element + b"\n")
            except InvalidMetadata as error:
                raise InvalidMetadata(str(error), number) from None
        write(_ENDS[kind])
    return Merged(kind, sink.getvalue(), opened.hexdigest(), size)


def repomd(revision: str, parts: Sequence[Merged], passed: Sequence[Data]) -> bytes:
    """The group's `repomd.xml`: its merged files, and what it passes on of a member's."""
    data = []
    for part in parts:
        checksum = hashlib.sha256(part.packed).hexdigest()
        data.append(
            f'  <data type="{part.kind}">\n'
            f'    <checksum type="sha256">{checksum}</checksum>\n'
            f'    <open-checksum type="sha256">{part.open_checksum}</open-checksum>\n'
            f'    <location href="repodata/{part.name}"/>\n'
            f"    <timestamp>{revision}</timestamp>\n"
            f"    <size>{len(part.packed)}</size>\n"
            f"    <open-size>{part.open_size}</open-size>\n"
            "  </data>\n".encode()
        )
    data.extend(b"  " + element.strip() + b"\n" for element in (each.element for each in passed))
    return (
        _START
        + b'<repomd xmlns="http://linux.duke.edu/metadata/repo" '
        + b'xmlns:rpm="http://linux.duke.edu/metadata/rpm">\n'
        + f"  <revision>{revision}</revision>\n".encode()
        + b"".join(data)
        + b"</repomd>\n"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/yum/test_merge.py -q`
Expected: 24 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/yum backend/tests/repositories/yum
git commit -m "feat: merge members' repodata by package, an earlier member's first, packed with zstd"
```

---

### Task 3: Groups of YUM repositories

**Files:**
- Create: `backend/src/megooarti/repositories/yum/groups.py`, `backend/tests/repositories/yum/test_groups.py`
- Modify: `backend/src/megooarti/repositories/yum/format.py`, `docs/formats/yum.md`
- Modify (tests): `backend/tests/repositories/yum/conftest.py`, `test_hosted.py`

**Interfaces:**
- Consumes: Tasks 1 and 2; plan 12c's `format.hosted_repodata`, `format.depth_of`, `format.repodata_content_type`, `paths.*`, `repodata.repodata`, `rpms.read`; plan 12b's `derived.written(..., stale=True)`, `derived.peek`, `group.leaves`, `group.TRY_NEXT`, `proxy.ensure_cached`.
- Produces: the `yum` format's types are hosted, proxy and group; a YUM proxy's `format_config.remote_keys`; `format.repodata_file(written, directory, filename) -> bytes | None`, `format.holds_packages(written, directory) -> bool`; `groups.RETRY`, `groups.handle_group(context, request, path, serve)`, and `groups._written(...)`, which a test counts. In the tests, `conftest.mirror_files(packages, root=, key=, comps=)`, `mirror_key()`, `written_behind()`, `MIRRORED_AT`, `ROOT`, `COMPS`.

- [ ] **Step 1: Write the failing tests**

Two tests of plan 12c change: a YUM proxy now takes `remote_keys` (so `repodata_depth` is refused at `format_config.repodata_depth`), and a YUM group can be made.

Change `backend/tests/repositories/yum/conftest.py`:

```diff
@@ -1,10 +1,16 @@
-"""YUM repositories made for a test, and what uploads to them."""
+"""YUM repositories made for a test, what uploads to them, and a mirror to proxy."""
+
+import asyncio
+import functools
+import hashlib
 
 import pytest
 
-from megooarti.repositories import derived, service
+from megooarti.repositories import derived, service, signing
 from megooarti.repositories.models import Repository
+from megooarti.repositories.yum import repodata, rpms
 from tests.accounts import PASSWORD, basic
+from tests.repositories.yum.packages import pieces
 
 URL = "/repository/yum-hosted"
 REMOTE = "http://remote.test/fedora/44/Everything/x86_64/os"
@@ -17,6 +23,7 @@ async def create(
     type: str = "hosted",
     hosted: dict | None = None,
     proxy: dict | None = None,
+    group: dict | None = None,
     format_config: dict | None = None,
 ) -> Repository:
     """A YUM repository, committed."""
@@ -29,12 +36,22 @@ async def create(
         blob_store="default",
         hosted=hosted,
         proxy=proxy,
+        group=group,
         format_config=format_config or {},
     )
     await db.commit()
     return repository
 
 
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
     """Every test writes its metadata anew: what one wrote is not served to the next."""
@@ -57,3 +74,53 @@ async def root(make_user) -> dict[str, str]:
 async def upload(client, headers, path: str, package: bytes, *, repository: str = "yum-hosted"):
     """A package sent as `curl --upload-file` sends it to its path."""
     return await client.put(f"/repository/{repository}/{path}", content=package, headers=headers)
+
+
+# --- A mirror, as a proxy's remote --------------------------------------------------
+
+MIRRORED_AT = 1792000000
+ROOT = REMOTE.removeprefix("http://remote.test/")
+COMPS = b'<?xml version="1.0" encoding="UTF-8"?>\n<comps>the mirror\'s package groups</comps>\n'
+
+
+@functools.cache
+def mirror_key() -> signing.Material:
+    """The key the stand-in mirror signs with, made once for every test."""
+    return signing.generate_openpgp("A Fedora mirror")
+
+
+async def mirror_files(
+    packages: dict[str, bytes],
+    *,
+    root: str = ROOT,
+    key: signing.Material | None = None,
+    comps: bool = True,
+) -> dict[str, bytes]:
+    """A mirror's repository, as the stand-in remote serves it, by path under its host.
+
+    `packages` are by their paths under the repository. Its `repomd.xml` names package
+    groups too, if `comps`; it is signed, with `key`, if a key is given.
+    """
+    listed = []
+    for path, data in packages.items():
+        rpm = await rpms.read(pieces(data))
+        sha256 = hashlib.sha256(data).hexdigest()
+        listed.append(repodata.Listed(path, len(data), sha256, MIRRORED_AT, rpm))
+    files = repodata.repodata(listed, MIRRORED_AT)
+    if comps:
+        digest = hashlib.sha256(COMPS).hexdigest()
+        files[f"{digest}-comps.xml"] = COMPS
+        element = (
+            f'  <data type="group">\n    <checksum type="sha256">{digest}</checksum>\n'
+            f'    <location href="repodata/{digest}-comps.xml"/>\n'
+            f"    <timestamp>{MIRRORED_AT}</timestamp>\n    <size>{len(COMPS)}</size>\n"
+            "  </data>\n"
+        )
+        files["repomd.xml"] = files["repomd.xml"].replace(
+            b"</repomd>", element.encode() + b"</repomd>"
+        )
+    if key is not None:
+        files["repomd.xml.asc"] = signing.Signer(key.private_key).detached(files["repomd.xml"])
+    mirrored = {f"{root}/repodata/{name}": data for name, data in files.items()}
+    mirrored.update({f"{root}/{path}": data for path, data in packages.items()})
+    return mirrored
```

Create `backend/tests/repositories/yum/test_groups.py`:

```python
"""A group of YUM repositories: one address and one key for its members' `repodata/`."""

import gzip
import re
from datetime import timedelta
from xml.etree import ElementTree

import pysequoia
import pytest
import zstandard

from megooarti.repositories import signing
from megooarti.repositories.yum import groups as yum_groups
from tests.accounts import error_code
from tests.repositories.yum.conftest import (
    COMPS,
    REMOTE,
    ROOT,
    create,
    mirror_files,
    mirror_key,
    upload,
    written_behind,
)
from tests.repositories.yum.packages import make_rpm

GROUP = "/repository/yum-public"
COMMON = "{http://linux.duke.edu/metadata/common}"
REPO = "{http://linux.duke.edu/metadata/repo}"
# The mirror's packages: one an earlier member holds the path of with another package,
# one an earlier member has too, and one of its own.
COLLIDING = "Packages/h/megooarti-hello-2.0-1.noarch.rpm"
SHARED = "Packages/b/bash-5.3-1.x86_64.rpm"
ITS_OWN = "Packages/m/megooarti-tool-0.3-1.x86_64.rpm"
MIRRORED = {
    COLLIDING: make_rpm(version="2.0"),
    SHARED: make_rpm("bash", "5.3", "1", "x86_64"),
    ITS_OWN: make_rpm("megooarti-tool", "0.3", "1", "x86_64"),
}


def verified(data: bytes, signature: bytes, public_key: bytes) -> bytes:
    """What a detached signature vouches for, checked with one public key. Raises if not."""
    signing.verify_detached(data, signature, [pysequoia.Cert.from_bytes(public_key)])
    return data


def unpacked(href: str, data: bytes) -> bytes:
    if href.endswith(".zst"):
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)
    return gzip.decompress(data)


async def metadata(client, headers, base: str) -> dict[str, bytes]:
    """A `repomd.xml`, and each file it names, unpacked where packed, by its type."""
    repomd = await client.get(f"{base}/repodata/repomd.xml", headers=headers)
    assert repomd.status_code == 200, repomd.text
    found = {"repomd": repomd.content}
    for data in ElementTree.fromstring(repomd.content).iter(f"{REPO}data"):
        href = data.find(f"{REPO}location").get("href")
        got = await client.get(f"{base}/{href}", headers=headers)
        assert got.status_code == 200, href
        found[data.get("type")] = (
            got.content if href.endswith(".xml") else unpacked(href, got.content)
        )
    return found


def locations(primary: bytes) -> list[str]:
    return [p.find(f"{COMMON}location").get("href") for p in ElementTree.fromstring(primary)]


@pytest.fixture
async def mirror(fake_remote):
    """A mirror with three packages and package groups; its repomd.xml is not signed."""
    fake_remote.files.update(await mirror_files(MIRRORED))
    return fake_remote


async def a_proxy(db, keys: str | None = None):
    return await create(
        db,
        "yum-fedora",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
        format_config={"remote_keys": keys} if keys else None,
    )


async def a_group(db, *members: str):
    return await create(db, "yum-public", type="group", group={"members": list(members)})


async def ours(client, root) -> None:
    """The hosted member's packages: one at a path the mirror has another at, and one
    the mirror has as well."""
    await upload(client, root, "megooarti-hello-1.0-1.noarch.rpm", make_rpm())
    await upload(client, root, COLLIDING, make_rpm("megooarti-other"))
    await upload(client, root, "bash.rpm", make_rpm("bash", "5.3", "1", "x86_64", summary="ours"))


async def test_a_directory_one_member_has_is_its_repomd_signed_with_the_groups_key(
    client, db, root, mirror
):
    await create(db, format_config={"repodata_depth": 2})
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "el10/x86_64/a.rpm", make_rpm())

    key = (await client.get(f"{GROUP}/public.key", headers=root)).content
    hosted = (
        await client.get("/repository/yum-hosted/el10/x86_64/repodata/repomd.xml", headers=root)
    ).content
    for base, original in (
        (f"{GROUP}/el10/x86_64", hosted),
        (GROUP, mirror.files[f"{ROOT}/repodata/repomd.xml"]),
    ):
        repomd = (await client.get(f"{base}/repodata/repomd.xml", headers=root)).content
        signature = (await client.get(f"{base}/repodata/repomd.xml.asc", headers=root)).content
        assert verified(repomd, signature, key) == original
    hosted_key = (await client.get("/repository/yum-hosted/public.key", headers=root)).content
    assert key != hosted_key


async def test_every_other_file_of_such_a_directory_comes_from_that_member(
    client, db, root, mirror
):
    await a_proxy(db)
    await a_group(db, "yum-fedora")

    found = await metadata(client, root, GROUP)

    assert sorted(locations(found["primary"])) == sorted(MIRRORED)
    assert found["group"] == COMPS


async def test_a_directory_several_members_have_is_merged_an_earlier_members_package_first(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await ours(client, root)

    found = await metadata(client, root, GROUP)

    assert locations(found["primary"]) == [
        COLLIDING,  # ours: megooarti-other, which the mirror's hello cannot take the place of
        "bash.rpm",  # ours, which the mirror has too
        "megooarti-hello-1.0-1.noarch.rpm",
        ITS_OWN,  # the mirror's own
    ]
    for kind in ("filelists", "other"):
        tree = ElementTree.fromstring(found[kind])
        assert [package.get("name") for package in tree] == [
            "megooarti-other",
            "bash",
            "megooarti-hello",
            "megooarti-tool",
        ]
    assert found["group"] == COMPS  # the mirror's, the first member that has them
    hrefs = re.findall(rb'href="(repodata/[^"]+)"', found["repomd"])
    assert [href.rsplit(b".", 1)[1] for href in hrefs] == [b"zst", b"zst", b"zst", b"xml"]


async def test_a_package_comes_from_the_first_member_that_has_its_path(client, db, root, mirror):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await ours(client, root)

    theirs = await client.get(f"{GROUP}/{ITS_OWN}", headers=root)
    mine = await client.get(f"{GROUP}/{COLLIDING}", headers=root)

    assert theirs.content == MIRRORED[ITS_OWN]
    assert mine.content == make_rpm("megooarti-other")


async def test_a_member_whose_file_is_not_the_one_its_repomd_names_is_left_out(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())
    primary = next(path for path in mirror.files if path.endswith("-primary.xml.gz"))
    mirror.files[primary] = gzip.compress(b"<metadata/>", mtime=0)

    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    # Until the proxy next reaches its remote, as the group's next request has it do.
    shown = (await client.get("/api/v1/repositories/yum-fedora", headers=root)).json()
    found = await metadata(client, root, GROUP)

    assert locations(found["primary"]) == ["a.rpm"]
    assert shown["status"]["last_error"].startswith("Left out of the group yum-public:")
    assert "not the one its repomd.xml names" in shown["status"]["last_error"]


@pytest.mark.parametrize(
    ("signer", "kept"),
    [("mirror", True), (None, False), ("another", False)],
)
async def test_a_proxy_given_its_remotes_keys_is_kept_only_if_they_signed_its_repomd(
    client, db, root, fake_remote, signer, kept
):
    key = {"mirror": mirror_key(), "another": signing.generate_openpgp("Another"), None: None}
    fake_remote.files.update(await mirror_files(MIRRORED, key=key[signer]))
    await create(db)
    await a_proxy(db, keys=mirror_key().public_key)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())

    found = await metadata(client, root, GROUP)

    assert (ITS_OWN in locations(found["primary"])) is kept


async def test_the_merged_metadata_is_written_once_for_each_state_of_the_members(
    client, db, root, mirror, monkeypatch
):
    written = []
    write = yum_groups._written

    async def counted(*arguments):
        written.append(1)
        return await write(*arguments)

    monkeypatch.setattr(yum_groups, "_written", counted)
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())

    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    await client.get(f"{GROUP}/repodata/repomd.xml.asc", headers=root)
    assert len(written) == 1
    await upload(client, root, "b.rpm", make_rpm(version="2.0"))
    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)  # written again, behind
    await written_behind()
    assert len(written) == 2
    again = await metadata(client, root, GROUP)
    assert "b.rpm" in locations(again["primary"])


async def test_while_a_member_cannot_be_checked_the_last_whole_metadata_is_kept(
    client, db, root, mirror, monkeypatch
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())
    whole = (await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)).content
    good = mirror.files[f"{ROOT}/repodata/repomd.xml"]
    mirror.files[f"{ROOT}/repodata/repomd.xml"] = b"not xml"

    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    await written_behind()
    held = (await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)).content
    mirror.files[f"{ROOT}/repodata/repomd.xml"] = good
    monkeypatch.setattr(yum_groups, "RETRY", timedelta(0))
    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    await written_behind()
    again = await metadata(client, root, GROUP)

    assert held == whole
    assert ITS_OWN in locations(again["primary"])


async def test_a_hosted_member_without_packages_adds_nothing_to_a_mirrors_directory(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")

    repomd = (await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)).content

    assert repomd == mirror.files[f"{ROOT}/repodata/repomd.xml"]


async def test_a_group_of_members_without_packages_has_empty_metadata(client, db, root):
    await create(db)
    await a_group(db, "yum-hosted")

    found = await metadata(client, root, GROUP)

    assert locations(found["primary"]) == []


@pytest.mark.parametrize("path", ["el9/repodata/repomd.xml", "repodata/primary.xml.gz"])
async def test_what_no_member_has_is_not_found(client, db, root, mirror, path):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")

    assert (await client.get(f"{GROUP}/{path}", headers=root)).status_code == 404


async def test_a_proxys_remote_keys_are_kept_and_shown(admin_client):
    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "yum-rocky",
            "format": "yum",
            "type": "proxy",
            "proxy": {"remote_url": "http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os"},
            "format_config": {"remote_keys": mirror_key().public_key},
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["format_config"] == {"remote_keys": mirror_key().public_key}


@pytest.mark.parametrize(
    ("type", "format_config", "field"),
    [
        ("proxy", {"remote_keys": "not a key"}, "format_config.remote_keys"),
        ("proxy", {"suite": "x"}, "format_config.suite"),
        ("group", {"repodata_depth": 1}, "format_config"),
    ],
)
async def test_settings_a_proxy_or_group_cannot_use_are_refused(
    admin_client, type, format_config, field
):
    body = {"name": "yum", "format": "yum", "type": type, "format_config": format_config}
    if type == "proxy":
        body["proxy"] = {"remote_url": REMOTE}
    else:
        body["group"] = {"members": []}

    refused = await admin_client.post("/api/v1/repositories", json=body)

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field
```

Change `backend/tests/repositories/yum/test_hosted.py`:

```diff
@@ -296,7 +296,7 @@ async def test_the_depth_is_chosen_when_the_repository_is_made_and_kept(admin_cl
         ("hosted", {"repodata_depth": "2"}, "format_config.repodata_depth"),
         ("hosted", {"repodata_depth": True}, "format_config.repodata_depth"),
         ("hosted", {"suite": "stable"}, "format_config.suite"),
-        ("proxy", {"repodata_depth": 1}, "format_config"),
+        ("proxy", {"repodata_depth": 1}, "format_config.repodata_depth"),
     ],
 )
 async def test_settings_that_cannot_be_used_are_refused(admin_client, type, format_config, field):
@@ -310,15 +310,6 @@ async def test_settings_that_cannot_be_used_are_refused(admin_client, type, form
     assert refused.json()["error"]["details"][0]["field"] == field
 
 
-async def test_a_group_of_yum_repositories_is_not_made_yet(admin_client):
-    refused = await admin_client.post(
-        "/api/v1/repositories",
-        json={"name": "yum-all", "format": "yum", "type": "group", "group": {"members": []}},
-    )
-
-    assert refused.status_code == 422
-
-
 async def test_what_an_empty_directorys_repomd_named_is_served_after_its_first_package(
     client, db, root
 ):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/yum -q`
Expected: 1 error during collection: `megooarti.repositories.yum` has no `groups`.

- [ ] **Step 3: Write the code and the guide**

Create `backend/src/megooarti/repositories/yum/groups.py`:

```python
"""Groups of YUM repositories: one address, one key, for the `repodata/` of all the members.

A group serves a `repodata/` in each directory where a member has one: a hosted
member in a directory as deep as its `repodata_depth` that holds packages, a proxy
member where its remote has `repodata/repomd.xml`. A client trusts the group's key and
nothing else, so the group checks what it signs: every file of a member that it reads
must have the checksum the member's `repomd.xml` names, and a proxy's `repomd.xml` must
be signed by one of its remote's keys where it was given them (`remote_keys`). A
member that fails a check is left out, its reason logged and kept as its last error.

A directory one member has is that member's: its `repomd.xml` signed again with the
group's key, and every other file sent on from it; dnf checks each against that
`repomd.xml`. In a directory several members have, the group writes `primary.xml`,
`filelists.xml` and `other.xml` from theirs, an earlier member's package first, and
names in its `repomd.xml` what else the first member that has it has (package groups,
updates, modules).

What a group writes of a directory is kept, by a digest of what its members' metadata
is now: a hosted member's revision, and a proxy's `repomd.xml`, its signature and its
keys. A request does not wait for the next one while one is kept, and holds no
database connection while it waits for the first. While a member that the last one
had cannot be checked, the last one is kept a while longer and tried again.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived, group, proxy, signing
from megooarti.repositories.checks import LeftOut, leave_out, members_in, remote_keys
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve
from megooarti.repositories.models import SigningKey
from megooarti.repositories.yum import format as yum
from megooarti.repositories.yum import merge, paths

# The most of a member's `repomd.xml` and of its signature that is read, and of one of
# its packed files.
REPOMD_MOST = 16 * 1024 * 1024
PACKED_MOST = 256 * 1024 * 1024
# How long what was written while a member was left out is served before another try.
RETRY = timedelta(minutes=1)
# The mark of a revision written while a member was left out: no digest ends so.
_INCOMPLETE = "~"
# Who answers for every file a group did not write itself, in `Written.routes`.
_ANY = "*"


@dataclass(frozen=True)
class Offer:
    """What one member has of a directory, checked."""

    member: RepositoryContext
    repomd: bytes
    said: merge.Repomd
    hosted: derived.Written | None  # a hosted member's own metadata; None for a proxy


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def _owned(kind: str) -> bool:
    """Whether a kind of file is one a group writes itself where it merges: the packages'
    lists, and every other form of them (`primary_db`, `filelists_zck`, ...)."""
    return kind.split("_")[0].split("-")[0] in merge.KINDS


def _in(directory: str, href: str) -> str:
    """A path under a directory, from what `repomd.xml` says of it."""
    return f"{directory}/{href}" if directory else href


async def _token(member: RepositoryContext, directory: str) -> str | None:
    """What a member's metadata of a directory is now, or None if it has none there."""
    if member.repository.type == "hosted":
        if not paths.at_depth(directory, yum.depth_of(member)):
            return None
        revision, _ = await member.revision()
        return f"{member.repository.id}:{revision}"
    found = []
    keys = remote_keys(member)
    for name in (paths.REPOMD, paths.SIGNATURE) if keys else (paths.REPOMD,):
        path = paths.in_repodata(directory, name)
        try:
            await proxy.ensure_cached(member, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            if name == paths.REPOMD:
                return None  # it does not have the directory, or cannot be asked now
        stored = await member.stat(path)
        if stored is None and name == paths.REPOMD:
            return None
        found.append(stored.sha256 if stored else "-")
    found.append(hashlib.sha256(keys.encode()).hexdigest())
    return f"{member.repository.id}:{':'.join(found)}"


async def _offer(member: RepositoryContext, directory: str) -> Offer:
    """What a member has of a directory, checked. Raises LeftOut."""
    hosted = None
    if member.repository.type == "hosted":
        hosted = await yum.hosted_repodata(member)
        repomd = yum.repodata_file(hosted, directory, paths.REPOMD)
    else:
        try:
            repomd = await member.read(
                paths.in_repodata(directory, paths.REPOMD), limit=REPOMD_MOST
            )
        except TooLarge:
            raise LeftOut("its repomd.xml is larger than this server reads") from None
        if repomd is None:
            raise LeftOut("its repomd.xml is gone")
        keys = remote_keys(member)
        if keys:
            await _check_signature(member, directory, repomd, keys)
    try:
        said = merge.parse_repomd(repomd)
    except merge.InvalidMetadata as error:
        raise LeftOut(str(error)) from None
    if "primary" not in said.data:
        raise LeftOut("its repomd.xml names no primary.xml")
    return Offer(member, repomd, said, hosted)


async def _check_signature(
    member: RepositoryContext, directory: str, repomd: bytes, keys: str
) -> None:
    try:
        signature = await member.read(
            paths.in_repodata(directory, paths.SIGNATURE), limit=REPOMD_MOST
        )
    except TooLarge:
        signature = None
    if signature is None:
        raise LeftOut("its remote did not sign its repomd.xml, which its keys could check")
    try:
        signing.verify_detached(repomd, signature, signing.read_public_keys(keys))
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    except signing.Unverified as error:
        raise LeftOut(f"its repomd.xml is not signed by its remote's keys: {error}") from None


async def _packed(offer: Offer, directory: str, data: merge.Data) -> bytes:
    """One of a member's files that its `repomd.xml` names, as it is packed, checked."""
    if offer.hosted is not None:
        packed = yum.repodata_file(offer.hosted, directory, data.href.removeprefix("repodata/"))
    else:
        path = _in(directory, data.href)
        try:
            await proxy.ensure_cached(offer.member, path)
            packed = await offer.member.read(path, limit=PACKED_MOST)
        except TooLarge:
            raise LeftOut(f"its {data.type} is larger than this server reads") from None
        except ApiError as error:
            raise LeftOut(f"its {data.type} cannot be fetched: {error.message}") from None
    if packed is None:
        raise LeftOut(f"its {data.type} is gone")
    try:
        merge.check(data, packed)
    except merge.InvalidMetadata as error:
        raise LeftOut(str(error)) from None
    return packed


async def _merged(
    context: RepositoryContext, offers: list[Offer], directory: str
) -> tuple[bytes, derived.Files, dict[str, uuid.UUID | None], bool]:
    """What the group writes of a directory several members have.

    Returns its `repomd.xml`, the files it names that the group wrote, which member
    answers for each of the others, and whether a member was left out of any of it.
    """
    incomplete = False
    primaries: list[tuple[Offer, bytes]] = []
    for offer in offers:
        try:
            primaries.append((offer, await _packed(offer, directory, offer.said.data["primary"])))
        except LeftOut as error:
            incomplete = True
            await leave_out(context, offer.member, str(error))
    while True:
        try:
            kept = await asyncio.to_thread(
                merge.kept,
                [(offer.said.data["primary"].href, packed) for offer, packed in primaries],
            )
            break
        except merge.InvalidMetadata as error:
            offer, _ = primaries.pop(error.args[1])
            incomplete = True
            await leave_out(context, offer.member, str(error.args[0]))
    taken = [offer for offer, _ in primaries]
    if not taken:
        raise LeftOut("no member's primary.xml could be read")
    parts = [
        await asyncio.to_thread(
            merge.merged,
            "primary",
            [(offer.said.data["primary"].href, packed) for offer, packed in primaries],
            kept,
        )
    ]
    for kind in ("filelists", "other"):
        files, sets = [], []
        for offer, mine in zip(taken, kept, strict=True):
            data = offer.said.data.get(kind)
            if data is None:
                continue
            try:
                files.append((data.href, await _packed(offer, directory, data)))
                sets.append(mine)
            except LeftOut as error:
                incomplete = True
                await leave_out(context, offer.member, str(error))
        try:
            parts.append(await asyncio.to_thread(merge.merged, kind, files, sets))
        except merge.InvalidMetadata as error:
            incomplete = True
            await leave_out(context, taken[error.args[1]].member, str(error.args[0]))
    routes: dict[str, uuid.UUID | None] = {}
    passed = []
    for offer in taken:
        for kind, data in offer.said.data.items():
            if _owned(kind) or any(other.type == kind for other in passed):
                continue
            passed.append(data)
            routes[data.href.removeprefix("repodata/")] = offer.member.repository.id
    # The newest of its members' files: the same members, the same bytes, in any process.
    moment = max(offer.said.moment for offer in taken) or int(utcnow().timestamp())
    repomd = merge.repomd(str(moment), parts, passed)
    return repomd, {part.name: part.packed for part in parts}, routes, incomplete


def _carried(previous: derived.Written | None) -> derived.Files:
    """What the group wrote of the last revision that its `repomd.xml` named."""
    if previous is None:
        return {}
    repomd = previous.files.get(paths.REPOMD, b"")
    return {
        name: data
        for name, data in previous.files.items()
        if paths.hashed(name) and f'href="repodata/{name}"'.encode() in repomd
    }


async def _written(
    context: RepositoryContext,
    offers: list[Offer],
    directory: str,
    signer: signing.Signer,
    previous: derived.Written | None,
) -> tuple[derived.Written, bool]:
    """The group's `repodata/` of a directory, and whether a member was left out of it."""
    if len(offers) == 1:
        repomd, files, incomplete = offers[0].repomd, {}, False
        routes: dict[str, uuid.UUID | None] = {_ANY: offers[0].member.repository.id}
    else:
        repomd, files, routes, incomplete = await _merged(context, offers, directory)
    if previous is not None:
        carried = _carried(previous)
        files = {**carried, **files}
        # Whoever answered for what the last `repomd.xml` named still does.
        named = previous.files.get(paths.REPOMD, b"")
        for name, member in previous.routes.items():
            if name == _ANY or f'href="repodata/{name}"'.encode() in named:
                routes.setdefault(name, member)
    files[paths.REPOMD] = repomd
    files[paths.SIGNATURE] = await asyncio.to_thread(signer.detached, repomd)
    return derived.Written("", utcnow(), files, routes), incomplete


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
    offers, left_out = [], False
    for member in await members_in(db, context, candidates):
        try:
            offers.append(await _offer(member, directory))
        except LeftOut as error:
            left_out = True
            await leave_out(context, member, str(error))
    # A hosted member's directory without packages adds nothing to another's.
    filled = [offer for offer in offers if not _empty(offer, directory)]
    offers = filled or offers[:1]
    previous = derived.peek(of)
    whole = previous is not None and not str(previous.revision).endswith(_INCOMPLETE)
    if left_out and whole:
        # Keep the last whole one while a member cannot be checked, and try again later.
        await db.commit()
        return replace(previous, held_until=now + RETRY)
    if not offers:
        await db.commit()
        raise _not_found("No repository of this group that has this directory could be checked.")
    signer = signing.signer(context.settings, key)
    try:
        written, incomplete = await _written(context, offers, directory, signer, previous)
    except LeftOut as error:
        await db.commit()
        raise _not_found(f"No repository of this group could be read: {error}") from None
    await db.commit()
    if left_out or incomplete:
        return replace(written, revision=revision + _INCOMPLETE, held_until=now + RETRY)
    return replace(written, revision=revision)


def _empty(offer: Offer, directory: str) -> bool:
    """Whether an offer is a hosted member's directory that holds no packages."""
    return offer.hosted is not None and not yum.holds_packages(offer.hosted, directory)


async def _directory_index(
    context: RepositoryContext, request: Request, directory: str
) -> tuple[derived.Written, dict[uuid.UUID, RepositoryContext]]:
    """What the group has of a directory, and its members that answer for it."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, directory)
        if token is not None:
            candidates.append(member.repository.id)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has metadata in this directory.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    revision = hashlib.sha256("\n".join([key.fingerprint, directory, *tokens]).encode()).hexdigest()
    # A request that waits for the writing holds no connection: the writing has its own.
    await context.release()
    sessions = request.app.state.sessionmaker

    async def write() -> derived.Written:
        async with sessions() as db:
            return await _write(db, context, candidates, directory, key, revision)

    of = (context.repository.id, directory)
    written = await derived.written(of, revision, write, stale=True)
    return written, {member.repository.id: member for member in members}


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """A directory's `repodata/` from what the group writes; anything else from a member."""
    parsed = paths.classify(path)
    if request.method not in ("GET", "HEAD") or parsed.kind != "repodata":
        return await group.handle_group(context, request, path, serve)
    written, members = await _directory_index(context, request, parsed.directory)
    data = written.files.get(parsed.filename)
    if data is not None:
        return context.respond_with(
            data,
            request,
            filename=parsed.filename,
            content_type=yum.repodata_content_type(parsed.filename),
            last_modified=written.changed,
            etag=hashlib.sha256(data).hexdigest(),
            dated=False,
        )
    if parsed.filename in (paths.REPOMD, paths.SIGNATURE):
        raise _not_found("No such file.")
    member = members.get(written.routes.get(parsed.filename) or written.routes.get(_ANY))
    if member is None:
        raise _not_found("No repository of this group has this file.")
    return await serve(member, request, path)
```

Change `backend/src/megooarti/repositories/yum/format.py`:

```diff
@@ -28,11 +28,12 @@ from starlette.responses import Response
 
 from megooarti.clock import utcnow
 from megooarti.errors import ApiError
-from megooarti.repositories import derived, signing
+from megooarti.repositories import checks, derived, signing
 from megooarti.repositories.content import RepositoryContext, Snapshot
 from megooarti.repositories.formats import (
     ComponentKey,
     Format,
+    Serve,
     Usage,
     declared_hashes,
     declared_size,
@@ -218,8 +219,10 @@ def _written(
     moment = int(snapshot.changed.timestamp())
     listed = _listed(snapshot, depth)
     # At depth 0 the root always has one; deeper, any directory without packages has
-    # the same, empty one.
-    listed.setdefault("" if depth == 0 else _EMPTY, [])
+    # the same, empty one, kept as well beside the root's, to tell an empty one by.
+    if depth == 0:
+        listed.setdefault("", [])
+    listed[_EMPTY] = []
     files = _carried(previous)
     for directory, packages in listed.items():
         for name, data in _signed(packages, moment, signer).items():
@@ -242,6 +245,26 @@ async def hosted_repodata(context: RepositoryContext) -> derived.Written:
     return await derived.written(context.repository.id, revision, write)
 
 
+def repodata_file(written: derived.Written, directory: str, filename: str) -> bytes | None:
+    """A file of a directory's `repodata/`, from what was written of a revision.
+
+    The directory is one as deep as the repository's `repodata_depth`.
+    """
+    data = written.files.get(paths.in_repodata(directory, filename))
+    own = paths.in_repodata(directory, paths.REPOMD) in written.files
+    if data is None and (not own or paths.hashed(filename)):
+        # A directory without packages has the empty one; a client that read its
+        # `repomd.xml` before the first package came still finds what it named.
+        data = written.files.get(paths.in_repodata(_EMPTY, filename))
+    return data
+
+
+def holds_packages(written: derived.Written, directory: str) -> bool:
+    """Whether a directory of a revision has packages in its `repodata/`."""
+    own = written.files.get(paths.in_repodata(directory, paths.REPOMD))
+    return own is not None and own != written.files.get(paths.in_repodata(_EMPTY, paths.REPOMD))
+
+
 def repodata_content_type(filename: str) -> str:
     if filename.endswith(".asc"):
         return _SIGNATURE
@@ -259,12 +282,7 @@ async def _repodata(
             f"This repository's metadata is {depth} directories down (repodata_depth)."
         )
     written = await hosted_repodata(context)
-    data = written.files.get(paths.in_repodata(parsed.directory, parsed.filename))
-    own = paths.in_repodata(parsed.directory, paths.REPOMD) in written.files
-    if data is None and (not own or paths.hashed(parsed.filename)):
-        # A directory without packages has the empty one; a client that read its
-        # `repomd.xml` before the first package came still finds what it named.
-        data = written.files.get(paths.in_repodata(_EMPTY, parsed.filename))
+    data = repodata_file(written, parsed.directory, parsed.filename)
     if data is None:
         raise _not_found("This repository's metadata has no such file.")
     return context.respond_with(
@@ -294,14 +312,16 @@ async def _public_key(context: RepositoryContext, request: Request) -> Response:
 
 class YumFormat(Format):
     name = "yum"
-    types = frozenset({"hosted", "proxy"})
+    types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
     signs = signing.OPENPGP
 
     def validate_config(
         self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
     ) -> dict[str, Any]:
-        """A hosted repository's `repodata_depth`, which never changes."""
+        """A hosted repository's `repodata_depth`, which never changes; a proxy's remote's keys."""
+        if repository_type == "proxy":
+            return checks.remote_keys_setting(config, "YUM")
         if repository_type != "hosted":
             return super().validate_config(repository_type, config, current)
         unknown = sorted(set(config) - {"repodata_depth"})
@@ -407,5 +427,15 @@ class YumFormat(Format):
             return await _repodata(context, request, parsed)
         raise _not_found()
 
+    async def handle_group(
+        self, context: RepositoryContext, request: Request, path: str, serve: Serve
+    ) -> Response:
+        if paths.classify(path).kind == "key" and _is_read(request):
+            return await _public_key(context, request)
+        # Imported here: it is written against this module.
+        from megooarti.repositories.yum import groups
+
+        return await groups.handle_group(context, request, path, serve)
+
 
 register(YumFormat())
```

Change `docs/formats/yum.md`:

````diff
@@ -112,10 +112,93 @@ would lead dnf past MegooArti.
   checked again with the remote after `metadata_max_age_minutes`; the files it names
   carry their hash in their names, and are kept, as packages are. A metalink or a
   mirror list is not proxied.
+- **A proxy's `remote_keys`**, its remote's public keys, armoured, are what a group it
+  is a member of checks its `repomd.xml` with. They are optional: Rocky Linux signs its
+  repositories' `repomd.xml`, Fedora does not.
+
+## Groups
+
+A group puts your own repositories and the mirrors behind one address, and signs the
+metadata it serves with a key of its own: a machine needs that one key for the
+metadata, and dnf goes on checking each package's own signature where `gpgcheck=1`.
+Give a proxy of a distribution that signs its metadata its keys, and the group checks
+them for the machines. For Rocky Linux's, on a machine that has them and jq:
+
+```bash
+keys=$(cat /etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10)
+jq -n --arg keys "$keys" '{
+  name: "yum-rocky", format: "yum", type: "proxy",
+  proxy: {remote_url: "http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os"},
+  format_config: {remote_keys: $keys}
+}' | curl -u admin -H 'Content-Type: application/json' -d @- \
+  http://localhost:8000/api/v1/repositories
+
+curl -u admin -H 'Content-Type: application/json' -d '{
+  "name": "yum-public", "format": "yum", "type": "group",
+  "group": {"members": ["yum-flat", "yum-rocky"]}
+}' http://localhost:8000/api/v1/repositories
+```
+
+Here `yum-flat` is a hosted repository at depth 0. On each machine, the group's key
+and the group:
+
+```bash
+curl -fsS -u ci -o /etc/pki/rpm-gpg/yum-public.asc \
+  https://repo.example.com/repository/yum-public/public.key
+cat > /etc/yum.repos.d/megooarti.repo <<EOF
+[megooarti]
+name=MegooArti
+baseurl=https://repo.example.com/repository/yum-public
+username=ci
+password=$MEGOOARTI_TOKEN
+repo_gpgcheck=1
+gpgcheck=0
+gpgkey=file:///etc/pki/rpm-gpg/yum-public.asc
+EOF
+```
+
+`gpgcheck=0`, as the packages of `yum-flat` are not signed; with them signed, give
+`gpgkey=` their key and the distribution's as well, and `gpgcheck=1`.
+
+- **The group serves a `repodata/` in each directory where a member has one**: a
+  hosted member in a directory as deep as its `repodata_depth` that holds packages, a
+  proxy where its remote has `repodata/repomd.xml`.
+- **A directory one member has** is that member's: its `repomd.xml`, signed again with
+  the group's key, and every file it names sent on from that member. dnf checks each
+  against that `repomd.xml`.
+- **A directory several members have** (a hosted repository at depth 0 beside a proxy
+  of Rocky's BaseOS, both at the root, as above) gets `primary.xml`, `filelists.xml`
+  and `other.xml` of the group's own, written from the members' and packed with zstd.
+  A package (the same name, epoch, version, release and architecture) that an earlier
+  member has is left out of a later one's, and so is a later member's package at a
+  path an earlier one holds with another package. Package groups (comps), updates
+  (updateinfo) and modules are not merged: the group names those of its first member
+  that has them, as that member gave them. The members' databases (`*.sqlite`) and
+  zchunk files are not named; dnf reads the XML.
+- **A member is checked before it is used**: every file the group reads of it must
+  have the checksum its `repomd.xml` names, and a proxy given `remote_keys` must have a
+  `repomd.xml.asc` that one of them made. A member that fails is left out, it is
+  logged, and the proxy's page says why as its last error until the proxy next
+  reaches its remote. While a member the last metadata had cannot be checked, that
+  metadata is kept a minute longer, and the group then tries again.
+- **The metadata is written again when a member's changes**, behind the requests: a
+  machine is given the last one meanwhile, and waits only the first time. The first
+  time takes as long as fetching the mirror's metadata and merging it: for Fedora's
+  whole release, 70 MB to fetch and about 17 seconds to merge with its updates. That
+  is longer than dnf waits for an answer, so ask for the group's `repomd.xml` once
+  (`curl -u ci https://repo.example.com/repository/yum-public/repodata/repomd.xml`)
+  before the machines do. What is merged of a directory is kept in memory: about
+  120 MB for Fedora's release and updates.
+- **Packages** are asked of the members in order, as in any group. A package's path
+  must therefore be the same file in every member that has it.
+- **The group's key** is made the first time it is needed, and is at
+  `/repository/<group>/public.key`, as a hosted repository's is.
 
 ## Clients
 
 Tested with dnf on Fedora 44 (dnf5) and Rocky Linux 10 (dnf 4): a package built with
 `rpmbuild`, uploaded two directories down and installed from a hosted repository with
-`repo_gpgcheck=1`; metadata signed with a key dnf was not given, refused; and a
-package from each distribution's mirror, installed through a proxy.
+`repo_gpgcheck=1`; metadata signed with a key dnf was not given, refused; a package
+from each distribution's mirror, installed through a proxy; and through groups: ours
+and the mirror's merged in one directory, a directory one member has, and, on Rocky
+Linux, a proxy given a key Rocky does not sign with left out.
````

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/yum tests/test_documents.py -q`
Expected: 325 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests docs
git commit -m "feat: YUM groups, one key for a directory of each member and for a directory they share"
```

---

### Task 4: dnf through groups, on Fedora and on Rocky Linux

**Files:**
- Modify: `backend/tests/test_yum_client.py`

**Interfaces:**
- Consumes: the stack built from the working tree, and plan 12c's fixtures of this module (`published`, `send`, `dnf`, `call`).
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the tests**

Change `backend/tests/test_yum_client.py`:

```diff
@@ -110,7 +110,9 @@ def said(result: subprocess.CompletedProcess[str]) -> str:
     return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
 
 
-def send(method: str, path: str, data: bytes | None = None) -> tuple[int, bytes]:
+def send(
+    method: str, path: str, data: bytes | None = None, *, timeout: int = 60
+) -> tuple[int, bytes]:
     """A request to a repository from outside, as `ci`: (status, body)."""
     credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
     request = urllib.request.Request(
@@ -120,7 +122,7 @@ def send(method: str, path: str, data: bytes | None = None) -> tuple[int, bytes]
         headers={"Authorization": f"Basic {credentials}"},
     )
     try:
-        with urllib.request.urlopen(request, timeout=60) as response:
+        with urllib.request.urlopen(request, timeout=timeout) as response:
             return response.status, response.read()
     except urllib.error.HTTPError as error:
         return error.code, error.read()
@@ -241,3 +243,127 @@ def test_dnf_installs_a_public_package_through_a_proxy_of_its_mirror(published,
 
     assert installed.returncode == 0, said(installed)
     assert installed.stdout.splitlines()[-1] == "42"
+
+
+# --- Groups ---------------------------------------------------------------------------
+
+ADMIN = "admin:'a brand new password'"  # what the `administrator` fixture made it
+FLAT = "yum-flat"
+# The guide's commands, as an administrator types them, against the stack: a proxy of
+# Rocky's BaseOS given Rocky's key, which signs its repomd.xml.
+GUIDE = f"""
+set -e
+dnf install -y -q jq > /dev/null
+keys=$(cat /etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10)
+jq -n --arg keys "$keys" '{{
+  name: "yum-rocky-keyed", format: "yum", type: "proxy",
+  proxy: {{remote_url: "{MIRRORS["rocky"]}", auto_block: false}},
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
+    """Four groups, with their keys saved beside the hosted repository's.
+
+    `yum-rocky-all` and `yum-fedora-all`: a hosted repository at depth 0 and a proxy of
+    each mirror, merged at the root. `yum-pass`: the hosted repository at depth 2 and
+    Rocky's proxy, which have no directory in common. `yum-wrong`: the one at depth 0,
+    and a proxy of Rocky given a key Rocky does not sign with.
+    """
+    result = subprocess.run(
+        ["docker", "run", "--rm", "--network", NETWORK, IMAGES["rocky"], "sh", "-c", GUIDE],
+        capture_output=True,
+        text=True,
+        encoding="utf-8",
+        errors="replace",
+        timeout=900,
+        check=False,
+    )
+    assert result.stdout.strip().endswith("made"), said(result)
+    made(administrator, {"name": FLAT, "format": "yum", "type": "hosted"})
+    package = (published / f"{PACKAGE}-1.0-1.noarch.rpm").read_bytes()
+    status, answer = send("PUT", f"{FLAT}/{PACKAGE}-1.0-1.noarch.rpm", package)
+    assert status == 201, answer
+    _, _, hosted_key = call("GET", f"/repositories/{HOSTED}/signing-key", headers=administrator)
+    made(
+        administrator,
+        {
+            "name": "yum-rocky-wrong",
+            "format": "yum",
+            "type": "proxy",
+            "proxy": {"remote_url": MIRRORS["rocky"], "auto_block": False},
+            # A key Rocky does not sign with: the hosted repository's own.
+            "format_config": {"remote_keys": hosted_key["public_key"]},
+        },
+    )
+    for name, members in (
+        ("yum-rocky-all", [FLAT, "yum-rocky-keyed"]),
+        ("yum-fedora-all", [FLAT, "yum-fedora"]),
+        ("yum-pass", [HOSTED, "yum-rocky-keyed"]),
+        ("yum-wrong", [FLAT, "yum-rocky-wrong"]),
+    ):
+        made(
+            administrator,
+            {"name": name, "format": "yum", "type": "group", "group": {"members": members}},
+        )
+        status, key = send("GET", f"{name}/public.key")
+        assert status == 200
+        (published / f"{name}.asc").write_bytes(key)
+    # The first time, a group fetches its members' metadata and merges it: for Fedora's
+    # whole release, a minute or more, longer than dnf waits for an answer.
+    for name in ("yum-rocky-all", "yum-fedora-all"):
+        status, answer = send("GET", f"{name}/repodata/repomd.xml", timeout=900)
+        assert status == 200, answer
+    return published
+
+
+def distribution_group(distribution: str) -> str:
+    return f"yum-{distribution}-all"
+
+
+@pytest.mark.parametrize("distribution", sorted(IMAGES))
+def test_dnf_installs_ours_and_the_mirrors_through_a_group_that_merges_them(groups, distribution):
+    name = distribution_group(distribution)
+    installed = dnf(
+        distribution,
+        groups,
+        f"with_dnf {name} /src/{name}.asc 1 0"
+        f" && dnf install -y {PACKAGE} bc && {PACKAGE} && echo '6 * 7' | bc",
+    )
+
+    assert installed.returncode == 0, said(installed)
+    assert installed.stdout.splitlines()[-2:] == [f"hello from {PACKAGE} 1.0", "42"]
+
+
+def test_dnf_installs_from_a_directory_one_member_of_a_group_has(groups):
+    installed = dnf(
+        "rocky",
+        groups,
+        "with_dnf yum-pass/rocky/x86_64 /src/yum-pass.asc 1 0"
+        f" && dnf install -y {PACKAGE} && {PACKAGE}",
+    )
+
+    assert installed.returncode == 0, said(installed)
+    assert installed.stdout.splitlines()[-1] == f"hello from {PACKAGE} 1.0"
+
+
+def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_of_a_group(groups, administrator):
+    installed = dnf(
+        "rocky",
+        groups,
+        "with_dnf yum-wrong /src/yum-wrong.asc 1 0"
+        f" && dnf install -y {PACKAGE} && {PACKAGE} && ! dnf install -y bc",
+    )
+    _, _, shown = call("GET", "/repositories/yum-rocky-wrong", headers=administrator)
+
+    assert installed.returncode == 0, said(installed)
+    assert shown["status"]["last_error"].startswith("Left out of the group yum-wrong")
```

- [ ] **Step 2: Run them**

They need a Docker daemon and internet access: Rocky's and Fedora's mirrors, and `jq` from Rocky's for the guide's commands. The first request to the group that merges Fedora's whole release fetches 70 MB of its metadata; the fixture makes it before dnf does, which would not wait that long.

Run (in `backend/`): `uv run pytest -m docker tests/test_yum_client.py -v`
Expected: 10 passed, in about five minutes once the images are pulled. If a proxy's test fails because a mirror is slow or away, run it again before reading anything into it.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_yum_client.py
git commit -m "test: dnf through groups: ours and a mirror's merged, one member's directory, a member left out"
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
@@ -173,6 +173,18 @@ What the server derives from the packages, it does not store (as Maven's metadat
 | R11 | A directory that had no packages keeps the files its empty `repomd.xml` named once its first package comes. | R4's machine, set up before the first upload, was given `404` for them. |
 | R12 | A hosted repository's metadata is written whole after each change, and the first request after it waits: 30,000 small packages take about 16 seconds to write and 4 more to read, a repository of 5,200 packages with a million files about 7. The guide says so. Writing only what changed (each package's part kept, each directory on its own) is left until a repository needs it. | Measured by the review on the reference laptop. dnf waits 30 seconds for a server that sends nothing. |
 
+### Settled while building plan 12d
+
+| # | What | Why |
+| --- | --- | --- |
+| S1 | A directory one member of a group has is that member's: its `repomd.xml`, signed again with the group's key, and every file it names sent on from that member. Only a directory several members have gets metadata of the group's own. | dnf checks every file against the `repomd.xml` it was given, and a YUM `repomd.xml` says nothing of whose repository it is that could change under a client (unlike APT's `Release`, Q10). Writing Fedora's metadata again would cost seconds and memory for nothing. |
+| S2 | A group merges its members' `primary.xml`, `filelists.xml` and `other.xml` by their `<package>` elements, copied as each member wrote them, without parsing a file whole, and packs what it writes with zstd. | Fedora 44's release and its updates: 1.3 GB of `filelists.xml`, merged in 17 seconds on the reference laptop with 245 MB at most in memory, 120 MB packed. Packed with gzip it would take most of a minute. dnf 5 on Fedora 44 and dnf 4 on Rocky Linux 10 read zstd. |
+| S3 | A merged directory's `repomd.xml` names the three files the group wrote, and of every other kind (package groups, updates, modules) the file of the first member that has it, as that member wrote its `<data>`. The members' `*.sqlite` and zchunk forms of the three are not named. Its revision and timestamps are the newest of its members' files' timestamps. | 6.4. dnf reads the XML. Rocky's `repomd.xml` gives its release (`10.2`) as its revision, not a time; the newest timestamp makes the same bytes in any process. |
+| S4 | Rocky Linux's mirrors sign their `repomd.xml` (`repomd.xml.asc`), Fedora's do not (in place of 6.4's "Fedora's and Rocky's mirrors do not"). A proxy given `remote_keys` must have a `repomd.xml.asc` that one of them made, or it is left out: a signature taken away is no reason to trust a remote less checked. | A group that skipped the check whenever the signature was missing would let whoever could change the mirror's answers skip it too. |
+| S5 | A hosted member's directory that holds no packages adds nothing where another member has the directory. A group whose members have no packages in a directory serves that directory's empty metadata. | A hosted repository at depth 0 always has a `repodata/`: beside a mirror, it would turn the mirror's own into a merge for nothing. |
+| S6 | What a group checks of a member, whatever the format, is in one module (`repositories/checks.py`): a proxy's `remote_keys` as a setting, leaving a member out, and the members as contexts of the writing's own session. APT's groups use it. `signing.verify_detached` checks a detached signature. | One way to leave a member out, and to say why. |
+| S7 | Fedora 44 and Rocky Linux 10 have no modules: section 11's risk of a group that passes on one member's `modules` concerns older distributions only (Rocky Linux 8 and 9's AppStream). The guide says that modules are the first member's. | Fedora dropped modularity in Fedora 39, and RHEL 10 has none. |
+
 ## 5. APT
 
 ### 5.1 Layout
@@ -300,7 +312,7 @@ For each directory, the group merges the members' `APKINDEX` (the same name, ver
 | A Python library for OpenPGP that signs as apt and dnf verify. | Settled for apt (P1) and dnf (R9): `pysequoia`. |
 | `zstd` packages need `zstandard` (Python 3.13 has no `zstd` of its own). | A dependency, added in plan 12a. |
 | Merging a proxy's whole index (Debian's `Packages` is tens of megabytes) costs memory and time on the first request after a change. | Measured in plan 12b (Q2): Debian's `main` for amd64, 69,908 packages, merged and packed in 2.4 seconds, 13 MB kept; a suite one member has is not merged at all (Q1). |
-| A YUM group passes on one member's `modules`: modular packages of the other members may be filtered by dnf. | Plan 12d's tests with Rocky's AppStream; the guide says what a group of modular repositories does. |
+| A YUM group passes on one member's `modules`: modular packages of the other members may be filtered by dnf. | Settled for Fedora 44 and Rocky Linux 10, which have none (S7); the guide says that a group passes on its first member's. |
 | Keys sealed with the secret key are lost with it. | The backup guide already says to keep the secret key; it will name signing keys too. |
 
 ## 12. Plans
```

- [ ] **Step 2: Run every suite**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3463 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; this plan changes nothing there.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, this plan's four new ones among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 12d settled"
```
