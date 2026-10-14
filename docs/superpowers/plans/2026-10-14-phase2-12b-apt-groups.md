# APT Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One group address, signed with one key of the group's own, serves the suites of its APT members, your own packages and a distribution's mirror alike, after checking each mirror's signatures for the client.

**Architecture:** A group finds, for each suite a client asks for, the members that have it: a hosted member whose suite it is, a proxy member whose remote has its `InRelease`. A proxy's `InRelease` is verified with the keys its remote was given (`remote_keys`); a member that fails is left out and says why. A suite one member has is that member's `Release`, signed again with the group's key, and every other file is sent on from that member. A suite several members have gets a `Release` of the group's own, in which a component and architecture several have is one `Packages.gz` merged from theirs, the earlier member's package first. What a group writes of a suite is kept in 12a's cache, by a digest of its members' state.

**Tech Stack:** Python 3.13, FastAPI, `pysequoia`; pytest; `debian:13` with GnuPG and jq for the guide's commands, and apt for the real-client tests.

**Spec:** [docs/superpowers/specs/2026-10-14-linux-package-formats-design.md](../specs/2026-10-14-linux-package-formats-design.md), sections 4.2, 4.4, 4.5, 5.4, 9, 10, 11 and the row of plan 12b in section 12, with what plan 12a settled (P1 to P12).

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| Q1 | A suite that one member of a group has is that member's, as it is: its `Release`, signed again with the group's key, and every other file of the suite, `by-hash/` paths included, sent on from that member. Only a suite several members have gets a `Release` of the group's own (spec 5.4), with `Acquire-By-Hash: no`. | apt checks every file against the `Release` it was given, and that one was checked against the remote's keys. Writing Debian's indexes again would cost seconds and memory for nothing, and lose its translations and `by-hash/` files. |
| Q2 | Where several members have a component and architecture, the group keeps `Packages.gz` alone; its `Release` names that and the text (`Packages`), which is not kept, with a `SHA256` list only. | Debian's `main` for amd64 is 57 MB of text and 13 MB packed: merged and packed with gzip in 2.4 seconds on the reference laptop, where xz would take most of a minute and keeping the text 57 MB of memory. apt finds an index by its text's name, and checks what it unpacks against it: without that line it did not fetch the merged index at all, as Task 5's first run showed. |
| Q3 | A merged suite does not list the architecture `all`. | Debian and Ubuntu list such packages in each architecture's `Packages`, as a hosted repository does. |
| Q4 | What a group writes of a suite is kept by the group and the suite, and by a digest of the group's key, a hosted member's revision, and a proxy member's `InRelease` and `remote_keys`. 12a's cache is told what it keeps (`Hashable`) and takes a digest as a revision. | Written again only when one of these changes. |
| Q5 | `Format.validate_member` refuses, when a group's members are set, an APT proxy without `remote_keys`. One whose keys are taken away later is left out when the group is asked. A member left out says why as its last error. | Spec 4.5. |
| Q6 | A proxy member whose remote has no `InRelease` is left out. A member whose `Packages` fails its check is left out of that component and architecture only. | Debian, Ubuntu and their mirrors have `InRelease`. |
| Q7 | A group's members are its leaves (12a's `group.leaves`): a group within a group gives its members, not its signed indexes. | One check of each remote, by the group the client trusts. |
| Q8 | `remote_keys` is armoured text, one or more keys, at most 1 MiB, and no private key. | Debian's keyring is binary; a JSON field is text. The guide makes it with `gpg --export --armor`. |

## Global Constraints

- **A client trusts the group's key and nothing else**: nothing a proxy member fetched is signed by the group unless the remote's own signature was verified first, and every file the group writes from a member's is checked against that member's `Release`.
- **What is read of a member is bounded** (spec 9): an `InRelease` at 16 MiB, a packed `Packages` at 256 MiB, unpacked at 1 GiB.
- **A format never touches a table or a file**: a group works through its members' contexts, `proxy.ensure_cached`, and `proxy_state.record_failure`.
- **Every test of a stack is marked `docker`.** The guide's commands are run by one, against the stack.
- **A table's line under its headings is `| --- | --- |`.** Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **A proxy member that changes between the group's `Release` and a client's next request**: a mirror updated, a cache entry replaced by `metadata_max_age_minutes`, a file the group passed on that no longer has the hash its `Release` names.
2. **What a group signs that it did not check**: a path under a suite the group sends on from a member, a top-level file of a merged suite, a member that is a group, a member that is offline.
3. **Large members**: Ubuntu's `universe`, several architectures, two proxies of the same distribution in one group; memory, time, and requests that wait for one another.
4. **Keys**: Ubuntu's keyring has bindings Sequoia's policy dates (SHA-1); a remote that rotates its key; `remote_keys` with a key that has expired; a key the group's own.
5. **What apt does with a group's `Release`**: two suites of one name from members of different distributions, `Suite`/`Codename` that differ from the path, a component one member names that another does not.

---

### Task 1: Reading a `Release`, and merging `Packages`

**Files:**
- Create: `backend/src/megooarti/repositories/apt/releases.py`, `merge.py`
- Create: `backend/tests/repositories/apt/test_releases.py`, `test_merge.py`, and in `backend/tests/repositories/apt/data/` Debian 13's `InRelease` (`debian-trixie-InRelease`) and Debian's archive keyring, armoured (`debian-archive-keyring.asc`)

**Interfaces:**
- Consumes: 12a's `control.parse`, `control.get`, `indexes.date`.
- Produces: `releases.Entry(size, sha256)`, `releases.Release(text, components, architectures, entries, moment)`, `releases.parse(text) -> Release` (raises `InvalidRelease`), `releases.compose(label=, suite=, moment=, components=, architectures=, entries=) -> bytes`; `merge.UNPACKED_MOST`, `merge.unpacked(name, data, most=...) -> bytes` (raises `InvalidIndex`), `merge.merged(texts) -> bytes`.

- [ ] **Step 1: Write the failing tests**

The two data files are Debian's own: `http://deb.debian.org/debian/dists/trixie/InRelease` as it was fetched on 14 October 2026, and `/usr/share/keyrings/debian-archive-keyring.gpg` of `debian:13`, armoured (`pysequoia.Cert.split_bytes`, then `str()` of each). Copy them from the plan's branch: the test reads that `InRelease`, signed in September 2026, with keys valid until 2029 and later.

Create `backend/tests/repositories/apt/test_releases.py`:

```python
from datetime import UTC, datetime

import pysequoia
import pytest

from megooarti.repositories.apt import releases
from megooarti.repositories.apt.releases import Entry
from tests.repositories.apt.packages import DATA

MOMENT = datetime(2026, 10, 14, 9, 30, 5, tzinfo=UTC)


def debians() -> bytes:
    """The text of Debian 13's `Release`, as its signature vouches for it."""
    keys = pysequoia.Cert.split_bytes((DATA / "debian-archive-keyring.asc").read_bytes())
    signed = (DATA / "debian-trixie-InRelease").read_bytes()
    return pysequoia.verify(bytes=signed, store=lambda _: keys).bytes


def test_debians_release_says_its_components_architectures_date_and_files():
    release = releases.parse(debians())

    assert release.components == ["main", "contrib", "non-free-firmware", "non-free"]
    assert "amd64" in release.architectures and "all" in release.architectures
    assert release.moment == datetime(2026, 9, 12, 7, 55, 41, tzinfo=UTC)
    entry = release.entries["main/binary-amd64/Packages.xz"]
    assert entry.size > 1_000_000 and len(entry.sha256) == 64
    assert release.text.endswith(b"\n")


def test_a_release_the_group_writes_is_read_back_as_it_was_written():
    entries = [
        ("main/binary-amd64/Packages", Entry(10, "a" * 64)),
        ("main/binary-amd64/Packages.gz", Entry(7, "b" * 64)),
    ]

    text = releases.compose(
        label="apt-public",
        suite="trixie",
        moment=MOMENT,
        components=["main", "contrib"],
        architectures=["amd64", "arm64"],
        entries=entries,
    )
    release = releases.parse(text)

    assert text.startswith(
        b"Origin: MegooArti\nLabel: apt-public\nSuite: trixie\nCodename: trixie\n"
        b"Date: Wed, 14 Oct 2026 09:30:05 UTC\nArchitectures: amd64 arm64\n"
        b"Components: main contrib\nAcquire-By-Hash: no\nSHA256:\n"
    )
    assert release.entries == dict(entries)
    assert (release.components, release.moment) == (["main", "contrib"], MOMENT)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (b"Origin: X\nSuite: a\n", "no SHA256 list"),
        (b"Suite: a\nSHA256:\n not a line\n", "cannot be read"),
        (b"\xff\xfe", "not a Release file"),
        (b"Suite: a\n\nSuite: b\n", "not a Release file"),
    ],
)
def test_a_release_that_cannot_be_read_is_refused(text, said):
    with pytest.raises(releases.InvalidRelease, match=said):
        releases.parse(text)


def test_a_date_that_cannot_be_read_is_no_date():
    release = releases.parse(b"Date: tomorrow\nSHA256:\n")

    assert release.moment is None
```

Create `backend/tests/repositories/apt/test_merge.py`:

```python
import gzip
import lzma

import pytest

from megooarti.repositories.apt import merge


def paragraph(name: str, version: str, architecture: str = "amd64", file: str = "x") -> bytes:
    return (
        f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n"
        f"Filename: pool/{file}.deb\nDescription: d\n continued\n"
    ).encode()


def packages(*paragraphs: bytes) -> bytes:
    return b"".join(one + b"\n" for one in paragraphs)


@pytest.mark.parametrize(
    ("name", "pack"),
    [
        ("Packages", lambda text: text),
        ("Packages.gz", gzip.compress),
        ("Packages.xz", lzma.compress),
    ],
)
def test_each_variant_of_packages_is_unpacked(name, pack):
    text = packages(paragraph("a", "1"))

    assert merge.unpacked(name, pack(text)) == text


@pytest.mark.parametrize(
    ("name", "pack"), [("Packages.gz", gzip.compress), ("Packages.xz", lzma.compress)]
)
def test_what_unpacks_to_more_than_is_read_is_refused(name, pack):
    with pytest.raises(merge.InvalidIndex, match="larger than this server reads"):
        merge.unpacked(name, pack(bytes(1001)), most=1000)


def test_what_is_not_packed_as_its_name_says_is_refused():
    with pytest.raises(merge.InvalidIndex, match="cannot be unpacked"):
        merge.unpacked("Packages.xz", b"plain text")


def test_packages_are_merged_in_order_and_a_package_an_earlier_one_has_is_left_out():
    ours = packages(paragraph("hello", "1.0", file="ours"), paragraph("tool", "2"))
    theirs = packages(
        paragraph("hello", "1.0", file="theirs"),
        paragraph("hello", "1.0", "arm64", file="theirs-arm"),
        paragraph("libc6", "2.41"),
    )

    text = merge.merged([ours, theirs])

    assert text.count(b"Package: ") == 4
    assert b"pool/ours.deb" in text and b"pool/theirs.deb" not in text
    assert b"pool/theirs-arm.deb" in text
    assert text.index(b"Package: tool") < text.index(b"Package: libc6")
    assert text.endswith(b"continued\n\n")


def test_a_paragraph_that_does_not_say_which_package_it_is_is_left_out():
    text = merge.merged([b"Package: a\nVersion: 1\n\nPackage: b\nVersion: 1\nArchitecture: all\n"])

    assert text == b"Package: b\nVersion: 1\nArchitecture: all\n\n"


def test_a_field_is_only_found_at_the_start_of_a_line():
    tricky = b"Package: a\nVersion: 1\nArchitecture: all\nDescription: x\n Package: b\n"

    assert (
        merge.merged([tricky, b"Package: b\nVersion: 1\nArchitecture: all\n"]).count(
            b"Package: b\nVersion"
        )
        == 1
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/apt/test_releases.py tests/repositories/apt/test_merge.py -q`
Expected: 2 errors during collection: `megooarti.repositories.apt` has no `releases` and no `merge`.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/repositories/apt/releases.py`:

```python
"""A suite's `Release`: what it says of itself, and of each file it names.

A group reads its members' `Release` files to know what each offers, and writes one of
its own for a suite that several members offer. Only the `SHA256` list is read and
written: it is what apt checks every file against.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from megooarti.repositories.apt import control
from megooarti.repositories.apt.indexes import date

# A line of a checksum list: the checksum, the size and the path under the suite.
_ENTRY = re.compile(r"([0-9a-f]{64})\s+([0-9]{1,18})\s+(\S+)")


class InvalidRelease(ValueError):
    """Text that is not a `Release` file a group can read."""


@dataclass(frozen=True)
class Entry:
    """A file a `Release` names: how large it is, and its SHA-256."""

    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    text: bytes  # as signed, with its last line ending
    components: list[str]
    architectures: list[str]
    entries: dict[str, Entry]  # by path under the suite
    moment: datetime | None  # its `Date`, if it says one


def parse(text: bytes) -> Release:
    """What a `Release` says. Raises InvalidRelease."""
    try:
        paragraph = control.parse(text.decode("utf-8"))
    except (UnicodeDecodeError, control.InvalidControl) as error:
        raise InvalidRelease(f"it is not a Release file: {error}") from None
    listed = control.get(paragraph, "SHA256")
    if listed is None:
        raise InvalidRelease("it has no SHA256 list")
    entries = {}
    for line in listed.strip().splitlines():
        found = _ENTRY.fullmatch(line.strip())
        if found is None:
            raise InvalidRelease(f"a line of its SHA256 list cannot be read: {line[:80]!r}")
        entries[found[3]] = Entry(int(found[2]), found[1])
    said = control.get(paragraph, "Date")
    try:
        moment = parsedate_to_datetime(said) if said else None
    except (TypeError, ValueError):
        moment = None
    return Release(
        text=text if text.endswith(b"\n") else text + b"\n",
        components=(control.get(paragraph, "Components") or "").split(),
        architectures=(control.get(paragraph, "Architectures") or "").split(),
        entries=entries,
        moment=moment,
    )


def compose(
    *,
    label: str,
    suite: str,
    moment: datetime,
    components: Sequence[str],
    architectures: Sequence[str],
    entries: Iterable[tuple[str, Entry]],
) -> bytes:
    """A group's `Release` of a suite several members offer."""
    lines = [
        "Origin: MegooArti",
        f"Label: {label}",
        f"Suite: {suite}",
        f"Codename: {suite}",
        f"Date: {date(moment)}",
        f"Architectures: {' '.join(architectures)}",
        f"Components: {' '.join(components)}",
        "Acquire-By-Hash: no",
        "SHA256:",
    ]
    for path, entry in sorted(entries):
        lines.append(f" {entry.sha256} {entry.size:>16} {path}")
    return ("\n".join(lines) + "\n").encode()
```

Create `backend/src/megooarti/repositories/apt/merge.py`:

```python
"""Members' `Packages` files made into one, the earlier member's package first.

A `Packages` file of a proxy can be tens of megabytes, so it is not parsed into
fields: each paragraph is kept as the bytes it was, and only the three fields that
say which package it is are looked for in it.
"""

import lzma
import re
import zlib
from collections.abc import Iterable

# The most a member's `Packages` file may be once unpacked (spec, section 9).
UNPACKED_MOST = 1024 * 1024 * 1024
_FIELDS = {
    name: re.compile(rb"^" + name + rb":[ \t]*(\S+)", re.MULTILINE)
    for name in (b"Package", b"Version", b"Architecture")
}


class InvalidIndex(ValueError):
    """A member's index that cannot be unpacked, or is larger than is read."""


def unpacked(name: str, data: bytes, most: int = UNPACKED_MOST) -> bytes:
    """A `Packages` file as text, from the variant `name` says it is."""
    try:
        if name.endswith(".xz"):
            text = lzma.LZMADecompressor().decompress(data, most + 1)
        elif name.endswith(".gz"):
            text = zlib.decompressobj(wbits=47).decompress(data, most + 1)
        else:
            text = data
    except (lzma.LZMAError, zlib.error) as error:
        raise InvalidIndex(f"{name} cannot be unpacked: {error}") from None
    if len(text) > most:
        raise InvalidIndex(f"{name} is larger than this server reads")
    return text


def _paragraphs(text: bytes) -> Iterable[bytes]:
    for paragraph in text.split(b"\n\n"):
        paragraph = paragraph.strip(b"\n")
        if paragraph:
            yield paragraph


def _key(paragraph: bytes) -> tuple[bytes, ...] | None:
    found = [pattern.search(paragraph) for pattern in _FIELDS.values()]
    if any(match is None for match in found):
        return None
    return tuple(match[1] for match in found)


def merged(texts: Iterable[bytes]) -> bytes:
    """One `Packages` file of several, in their order.

    A package (its name, version and architecture) that an earlier one has is left
    out of a later one, and a paragraph that does not say which package it is goes.
    """
    seen: set[tuple[bytes, ...]] = set()
    kept = []
    for text in texts:
        for paragraph in _paragraphs(text):
            key = _key(paragraph)
            if key is None or key in seen:
                continue
            seen.add(key)
            kept.append(paragraph + b"\n\n")
    return b"".join(kept)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/apt/test_releases.py tests/repositories/apt/test_merge.py -q`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/apt backend/tests/repositories/apt
git commit -m "feat: read what a suite's Release says, and merge members' Packages, the earlier first"
```

---

### Task 2: A remote's keys, and a group's own

**Files:**
- Modify: `backend/src/megooarti/repositories/signing.py`, `backend/tests/repositories/test_signing.py`

**Interfaces:**
- Consumes: Task 1's data files.
- Produces: `signing.KeysUnusable`, `signing.Unverified`, `signing.PUBLIC_KEYS_MOST`; `signing.read_public_keys(text) -> list[Cert]`; `signing.verify_clear(signed, certificates) -> bytes` (the text the signature vouches for); `signing.signs(repository)` is the format's kind for a group too, where the format has groups.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/test_signing.py`:

```diff
@@ -246,3 +246,52 @@ async def test_the_api_says_a_repository_that_signs_nothing_has_no_key(admin_cli
     answer = await admin_client.get(KEYS)
 
     assert (answer.status_code, error_code(answer)) == (404, "not_found")
+
+
+def test_a_remotes_public_keys_are_read_from_armoured_text():
+    keys = signing.read_public_keys(
+        (DATA / "debian-archive-keyring.asc").read_text(encoding="utf-8")
+    )
+
+    assert len(keys) == 9
+
+
+@pytest.mark.parametrize(
+    ("text", "said"),
+    [
+        ("not a key", "not one or more OpenPGP public keys"),
+        ((DATA / "plain-rsa.asc").read_text(encoding="utf-8"), "holds a private key"),
+        ("x" * (signing.PUBLIC_KEYS_MOST + 1), "longer than this server keeps"),
+    ],
+    ids=["text", "private", "long"],
+)
+def test_text_that_is_not_public_keys_is_refused(text, said):
+    with pytest.raises(signing.KeysUnusable, match=said):
+        signing.read_public_keys(text)
+
+
+def test_a_clear_signed_message_is_read_if_one_of_the_keys_signed_it():
+    keys = signing.read_public_keys(
+        (DATA / "debian-archive-keyring.asc").read_text(encoding="utf-8")
+    )
+    signed = (DATA / "debian-trixie-InRelease").read_bytes()
+
+    text = signing.verify_clear(signed, keys)
+
+    assert text.startswith(b"Origin: Debian\nLabel: Debian\n")
+
+
+def test_a_clear_signed_message_none_of_the_keys_signed_is_refused():
+    other = signing.read_public_keys(signing.generate_openpgp("Someone else").public_key)
+    signed = (DATA / "debian-trixie-InRelease").read_bytes()
+    altered = signed.replace(b"Origin: Debian", b"Origin: Debiam")
+    debian = signing.read_public_keys(
+        (DATA / "debian-archive-keyring.asc").read_text(encoding="utf-8")
+    )
+
+    with pytest.raises(signing.Unverified):
+        signing.verify_clear(signed, other)
+    with pytest.raises(signing.Unverified):
+        signing.verify_clear(altered, debian)
+    with pytest.raises(signing.Unverified):
+        signing.verify_clear(b"Origin: Debian\n", debian)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_signing.py -q`
Expected: 1 error during collection: `signing` has no `PUBLIC_KEYS_MOST` (nor what the other tests use).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/signing.py`:

```diff
@@ -39,6 +39,18 @@ class KeyUnusable(ValueError):
     """Text that is not a private key this server can sign with."""
 
 
+class KeysUnusable(ValueError):
+    """Text that is not one or more OpenPGP public keys."""
+
+
+class Unverified(ValueError):
+    """A signature that none of the keys it was checked with made, or that is not one."""
+
+
+# The most a remote's public keys may be: Debian's whole keyring is 56 KiB.
+PUBLIC_KEYS_MOST = 1024 * 1024
+
+
 @dataclass(frozen=True)
 class Material:
     """A key as it is stored, before its private part is sealed."""
@@ -108,10 +120,45 @@ class Signer:
         return pysequoia.sign(self._signer, data, mode=pysequoia.SignatureMode.DETACHED)
 
 
+def read_public_keys(text: str) -> list[object]:
+    """The OpenPGP public keys in armoured text: a remote's, which a group checks it with.
+
+    Raises KeysUnusable for text that has none, is too long, or holds a private key.
+    """
+    if len(text.encode()) > PUBLIC_KEYS_MOST:
+        raise KeysUnusable("The keys are longer than this server keeps.")
+    try:
+        certificates = pysequoia.Cert.split_bytes(text.encode())
+    except RuntimeError:
+        certificates = []
+    if not certificates:
+        raise KeysUnusable("This is not one or more OpenPGP public keys, armoured.")
+    if "PRIVATE KEY BLOCK" in text:
+        raise KeysUnusable("This holds a private key. Give the public keys only.")
+    return certificates
+
+
+def verify_clear(signed: bytes, certificates: list[object]) -> bytes:
+    """The text a clear-signed message (an `InRelease`) says, if one of the keys signed it.
+
+    Raises Unverified otherwise.
+    """
+    try:
+        return pysequoia.verify(bytes=signed, store=lambda _: certificates).bytes
+    except RuntimeError as error:
+        raise Unverified(str(error).splitlines()[0]) from None
+
+
 def signs(repository: Repository) -> str | None:
-    """The kind of key this repository signs with, or None if it signs nothing."""
+    """The kind of key this repository signs with, or None if it signs nothing.
+
+    A hosted repository signs the indexes it writes, and a group those it puts together
+    from its members'. A proxy passes its remote's signatures on, and has none.
+    """
     format = get_format(repository.format)
-    if format is None or repository.type != "hosted":
+    if format is None or repository.type not in ("hosted", "group"):
+        return None
+    if repository.type == "group" and "group" not in format.types:
         return None
     return format.signs
 
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/test_signing.py -q`
Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "feat: read a remote's public keys and check a clear signature with them; groups sign"
```

---

### Task 3: What a group's member may be, and a cache that keeps a group's suites

**Files:**
- Modify: `backend/src/megooarti/repositories/derived.py`, `formats.py`, `service.py`, `docs/adding-a-format.md`
- Modify (tests): `backend/tests/repositories/test_revisions.py`, `test_formats.py`

**Interfaces:**
- Consumes: nothing of Tasks 1 and 2.
- Produces: `Format.validate_member(member: Repository) -> None` (raises a 422 at `group.members`), called by `service._set_members` for each member; `derived.Written(revision: int | str, changed, files, routes: dict[str, uuid.UUID | None] = {})`; `derived.get/put/written` keyed by any `Hashable`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/test_revisions.py`:

```diff
@@ -236,3 +236,24 @@ async def test_a_failure_to_write_is_given_to_every_request_that_waited_and_kept
     assert derived.get(repository, 1) is None
     assert derived._writing == {}
     derived.forget()
+
+
+def test_what_a_digest_names_is_replaced_by_what_any_other_digest_names():
+    derived.forget()
+    suite = (uuid.uuid4(), "trixie")
+
+    derived.put(suite, derived.Written("b" * 64, utcnow(), {"Release": b"one"}))
+    derived.put(suite, derived.Written("a" * 64, utcnow(), {"Release": b"two"}))
+
+    assert derived.get(suite, "b" * 64) is None
+    assert derived.get(suite, "a" * 64).files == {"Release": b"two"}
+    derived.forget()
+
+
+def test_a_groups_written_files_say_which_member_answers_for_the_others():
+    member = uuid.uuid4()
+
+    written = derived.Written("a" * 64, utcnow(), {}, {"*": member})
+
+    assert written.routes == {"*": member}
+    assert derived.Written(1, utcnow(), {}).routes == {}
```

Change `backend/tests/repositories/test_formats.py`:

```diff
@@ -1,6 +1,7 @@
 import pytest
 
 from megooarti.errors import ApiError
+from megooarti.repositories import service
 from megooarti.repositories.formats import ComponentKey, Format, format_names, get_format, register
 from megooarti.repositories.raw import RawFormat
 
@@ -69,3 +70,56 @@ def test_the_generic_content_type_is_whatever_the_client_declared():
 
 def test_settings_validation_is_given_the_stored_settings():
     assert get_format("raw").validate_config("hosted", {}, {}) == {}
+
+
+class Choosy(RawFormat):
+    """Raw, as a format whose groups take no proxy."""
+
+    def validate_member(self, member):
+        if member.type == "proxy":
+            raise ApiError(
+                422,
+                "validation_error",
+                "The request is not valid.",
+                [{"field": "group.members", "message": f"{member.name} is a proxy."}],
+            )
+
+
+async def test_a_format_may_refuse_a_repository_as_a_member_of_its_groups(db, monkeypatch):
+    for name, type, settings in (
+        ("files", "hosted", {}),
+        ("mirror", "proxy", {"proxy": {"remote_url": "http://remote.test/files"}}),
+    ):
+        await service.create_repository(
+            db, name=name, format="raw", type=type, online=True, blob_store=None, **settings
+        )
+    monkeypatch.setattr(service, "get_format", lambda name: Choosy())
+
+    taken = await service.create_repository(
+        db,
+        name="ours",
+        format="raw",
+        type="group",
+        online=True,
+        blob_store=None,
+        group={"members": ["files"]},
+    )
+    with pytest.raises(ApiError) as refused:
+        await service.create_repository(
+            db,
+            name="everything",
+            format="raw",
+            type="group",
+            online=True,
+            blob_store=None,
+            group={"members": ["files", "mirror"]},
+        )
+
+    assert taken.name == "ours"
+    assert refused.value.details == [{"field": "group.members", "message": "mirror is a proxy."}]
+
+
+def test_the_generic_format_takes_any_member():
+    from megooarti.repositories.models import Repository
+
+    assert get_format("raw").validate_member(Repository(name="mirror", type="proxy")) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_revisions.py tests/repositories/test_formats.py -q`
Expected: 4 failed, 24 passed: `Written` takes no routes, the cache keeps the older of two digests, and no format has `validate_member`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/derived.py`:

```diff
@@ -1,11 +1,13 @@
-"""Index files written from a snapshot of a repository, kept in this process.
+"""Index files written from what repositories hold, kept in this process.
 
-They are kept by repository and revision: a revision's files are the same whenever
-they are written, so once written they are served until the repository changes. A
-newer revision of a repository takes the place of the older ones, and what is kept of
-all repositories together is bounded by its size: the least recently used goes first.
-While one request writes a revision's files, the others that want them wait for those,
-and none writes them a second time.
+They are kept by what they are of, a hosted repository or a suite of a group, and by
+the revision of it they were written from: a revision's files are the same whenever
+they are written, so once written they are served until it changes. A hosted
+repository's revision is the number its row counts; a group's is a digest of its
+members' own. A newer revision takes the place of the older ones, and what is kept of
+all of them together is bounded by its size: the least recently used goes first. While
+one request writes a revision's files, the others that want them wait for those, and
+none writes them a second time.
 
 Each process keeps its own; two that write the same revision write the same bytes, but
 for the signatures, which are each valid.
@@ -14,49 +16,62 @@ for the signatures, which are each valid.
 import asyncio
 import uuid
 from collections import OrderedDict
-from collections.abc import Awaitable, Callable
-from dataclasses import dataclass
+from collections.abc import Awaitable, Callable, Hashable
+from dataclasses import dataclass, field
 from datetime import datetime
 
 # How much is kept, of every repository together.
 MOST_BYTES = 256 * 1024 * 1024
 
 type Files = dict[str, bytes]
+type Revision = int | str
 
 
 @dataclass(frozen=True)
 class Written:
-    """The index files of one revision of a repository, and when the revision was made."""
+    """The index files of one revision, and when the revision was made.
 
-    revision: int
+    `routes` says, for a group, which member answers for a path that is not among the
+    files: by its first two parts (a component's architecture), its first (a component),
+    or `*` for any other. None says that none does.
+    """
+
+    revision: Revision
     changed: datetime
     files: Files
+    routes: dict[str, uuid.UUID | None] = field(default_factory=dict)
 
     @property
     def size(self) -> int:
         return sum(len(data) for data in self.files.values())
 
 
-_kept: OrderedDict[uuid.UUID, Written] = OrderedDict()
-_writing: dict[tuple[uuid.UUID, int], asyncio.Future[Written]] = {}
+_kept: OrderedDict[Hashable, Written] = OrderedDict()
+_writing: dict[tuple[Hashable, Revision], asyncio.Future[Written]] = {}
 
 
-def get(repository_id: uuid.UUID, revision: int) -> Written | None:
-    """What is kept of this revision, if it is the one kept of its repository."""
-    kept = _kept.get(repository_id)
+def get(of: Hashable, revision: Revision) -> Written | None:
+    """What is kept of this revision, if it is the one kept of what it is of."""
+    kept = _kept.get(of)
     if kept is None or kept.revision != revision:
         return None
-    _kept.move_to_end(repository_id)
+    _kept.move_to_end(of)
     return kept
 
 
-def put(repository_id: uuid.UUID, written: Written) -> None:
-    """Keep a revision's files, unless a newer revision of the repository is kept already."""
-    kept = _kept.get(repository_id)
-    if kept is not None and kept.revision > written.revision:
+def _older(kept: Written, written: Written) -> bool:
+    """Whether `written` is of an older revision than what is kept. Digests have no order."""
+    numbers = isinstance(kept.revision, int) and isinstance(written.revision, int)
+    return numbers and kept.revision > written.revision
+
+
+def put(of: Hashable, written: Written) -> None:
+    """Keep a revision's files, unless a newer revision of the same is kept already."""
+    kept = _kept.get(of)
+    if kept is not None and _older(kept, written):
         return
-    _kept[repository_id] = written
-    _kept.move_to_end(repository_id)
+    _kept[of] = written
+    _kept.move_to_end(of)
     total = sum(one.size for one in _kept.values())
     while total > MOST_BYTES and len(_kept) > 1:
         _, dropped = _kept.popitem(last=False)
@@ -64,17 +79,17 @@ def put(repository_id: uuid.UUID, written: Written) -> None:
 
 
 async def written(
-    repository_id: uuid.UUID, revision: int, make: Callable[[], Awaitable[Written]]
+    of: Hashable, revision: Revision, make: Callable[[], Awaitable[Written]]
 ) -> Written:
     """A revision's files: kept, being written by another request, or written by `make`.
 
     `make` may write a newer revision than was asked for, if the repository changed
     meanwhile: that is what every request that waited is then given.
     """
-    kept = get(repository_id, revision)
+    kept = get(of, revision)
     if kept is not None:
         return kept
-    key = (repository_id, revision)
+    key = (of, revision)
     pending = _writing.get(key)
     if pending is None:
         # A task of its own: a request that goes away does not stop it for the others.
@@ -84,7 +99,7 @@ async def written(
         def done(task: asyncio.Future[Written]) -> None:
             _writing.pop(key, None)
             if not task.cancelled() and task.exception() is None:
-                put(repository_id, task.result())
+                put(of, task.result())
 
         pending.add_done_callback(done)
     return await asyncio.shield(pending)
```

Change `backend/src/megooarti/repositories/formats.py`:

```diff
@@ -21,6 +21,7 @@ from megooarti.repositories.paths import normalise_path
 if TYPE_CHECKING:
     from megooarti.repositories.content import RepositoryContext
     from megooarti.repositories.forms import UploadForm
+    from megooarti.repositories.models import Repository
 
 # The dispatcher, as an engine sees it: answer this request from that repository.
 Serve = Callable[["RepositoryContext", Request, str], Awaitable[Response]]
@@ -144,6 +145,13 @@ class Format:
             raise ApiError(422, "validation_error", "The request is not valid.", details)
         return {}
 
+    def validate_member(self, member: "Repository") -> None:
+        """Refuse a repository that a group of this format cannot have as a member.
+
+        It is of this format, and is about to be one of a group's members. Raises a 422.
+        The generic format takes any.
+        """
+
     def default_deployment_policy(self, config: dict[str, Any]) -> str:
         """The deployment policy of a hosted repository that was given none.
 
```

Change `backend/src/megooarti/repositories/service.py`:

```diff
@@ -214,6 +214,7 @@ async def _set_members(db: AsyncSession, group: Repository, names: list[str]) ->
             raise _invalid("group.members", f"Unknown repository: {name}.")
         if member.format != group.format:
             raise _invalid("group.members", f"{name} is not a {group.format} repository.")
+        get_format(group.format).validate_member(member)
         chosen.append(member)
     if group.id in await _reachable(db, [member.id for member in chosen]):
         raise ApiError(
```

Change `docs/adding-a-format.md`:

```diff
@@ -63,6 +63,7 @@ raises.
 | `signs` | The kind of key a hosted repository signs its indexes with (`openpgp`). It is made the first time it is needed, and kept sealed | none |
 | `validate_name` | Refuse a repository name the format cannot be used under | any name |
 | `validate_config` | Check and return the format's own settings (`format_config`), and refuse a change that cannot be made | no settings |
+| `validate_member` | Refuse a repository a group of the format cannot have as a member (an APT proxy without its remote's keys) | any |
 | `default_deployment_policy` | The policy of a hosted repository that was given none | `allow_redeploy` |
 | `describe_component` | Which component (namespace, name, version) a stored file belongs to, from its path and what was recorded about it at upload, or none | the file, in its folder |
 | `search_text` | The words a component is found by | namespace, name and version |
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/test_revisions.py tests/repositories/test_formats.py tests/repositories/test_group.py tests/test_documents.py -q`
Expected: 189 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src docs/adding-a-format.md backend/tests
git commit -m "feat: a format may refuse a group's member; the index cache keeps what a digest names"
```

---

### Task 4: APT groups

**Files:**
- Create: `backend/src/megooarti/repositories/apt/groups.py`, `backend/tests/repositories/apt/test_groups.py`
- Modify: `backend/src/megooarti/repositories/apt/format.py`, `docs/formats/apt.md`
- Modify (tests): `backend/tests/repositories/apt/conftest.py` (a group parameter, and a stand-in mirror that signs its suite), `test_hosted.py` (a proxy's and a group's settings)

**Interfaces:**
- Consumes: Task 1 (`releases`, `merge`), Task 2 (`read_public_keys`, `verify_clear`, groups sign), Task 3 (`validate_member`, `derived` keyed by `(group id, suite)` with a digest), 12a's `proxy.ensure_cached`, `group.leaves`, `proxy_state.record_failure`.
- Produces: the `apt` format's `group` type; in `apt/format.py`, `suite_of(context)`, `hosted_indexes(context)`, `index_content_type(filename)` (were private), `format_config.remote_keys` for a proxy; `apt.groups.handle_group(context, request, path, serve)`, `groups._merged(context, offers, suite, signer)` (the tests count its calls).

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/apt/conftest.py`:

```diff
@@ -1,8 +1,14 @@
-"""APT repositories made for a test, and what uploads to them."""
+"""APT repositories made for a test, what uploads to them, and a mirror to proxy."""
+
+import functools
+import hashlib
+import lzma
+from datetime import UTC, datetime
 
 import pytest
 
-from megooarti.repositories import derived, service
+from megooarti.repositories import derived, service, signing
+from megooarti.repositories.apt import releases
 from megooarti.repositories.models import Repository
 from tests.accounts import PASSWORD, basic
 
@@ -17,6 +23,7 @@ async def create(
     type: str = "hosted",
     hosted: dict | None = None,
     proxy: dict | None = None,
+    group: dict | None = None,
     format_config: dict | None = None,
 ) -> Repository:
     """An APT repository, committed."""
@@ -29,6 +36,7 @@ async def create(
         blob_store="default",
         hosted=hosted,
         proxy=proxy,
+        group=group,
         format_config=format_config or {},
     )
     await db.commit()
@@ -61,3 +69,61 @@ async def upload(
     return await client.request(
         method, f"/repository/{repository}/", content=package, headers=headers
     )
+
+
+# --- A mirror, as a proxy's remote --------------------------------------------------
+
+
+@functools.cache
+def mirror_key() -> signing.Material:
+    """The key the stand-in mirror signs with, made once for every test."""
+    return signing.generate_openpgp("A Debian mirror")
+
+
+def mirror_files(
+    suite: str,
+    packages: dict[str, bytes],
+    *,
+    key: signing.Material | None = None,
+    root: str = "debian",
+) -> dict[str, bytes]:
+    """A mirror's suite, as the stand-in remote serves it, by path under its host.
+
+    `packages` are the text of each `Packages` file, by its directory under the suite
+    (`main/binary-amd64`). Each is served as `Packages.xz`, and `InRelease` names them.
+    """
+    files, entries = {}, []
+    for directory, text in packages.items():
+        packed = lzma.compress(text)
+        files[f"dists/{suite}/{directory}/Packages.xz"] = packed
+        entries.append(
+            (
+                f"{directory}/Packages.xz",
+                releases.Entry(len(packed), hashlib.sha256(packed).hexdigest()),
+            )
+        )
+    components = sorted({directory.split("/")[0] for directory in packages})
+    architectures = sorted({directory.split("-")[-1] for directory in packages})
+    release = releases.compose(
+        label="Mirror",
+        suite=suite,
+        moment=datetime(2026, 9, 12, 7, 55, 41, tzinfo=UTC),
+        components=components,
+        architectures=architectures,
+        entries=entries,
+    )
+    signer = signing.Signer((key or mirror_key()).private_key)
+    files[f"dists/{suite}/InRelease"] = signer.clear(release)
+    return {f"{root}/{path}": data for path, data in files.items()}
+
+
+def paragraph(
+    name: str, version: str, architecture: str = "amd64", file: str | None = None
+) -> bytes:
+    """A package as a mirror's `Packages` lists it."""
+    filename = file or f"pool/main/{name[0]}/{name}/{name}_{version}_{architecture}.deb"
+    return (
+        f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n"
+        f"Filename: {filename}\nSize: 1\nSHA256: {'0' * 64}\n"
+        f"Description: {name} from the mirror\n\n"
+    ).encode()
```

Create `backend/tests/repositories/apt/test_groups.py`:

```python
"""A group of APT repositories: one address and one key for its members' suites."""

import gzip
import hashlib
import lzma

import pysequoia
import pytest

from megooarti.repositories.apt import control, releases
from megooarti.repositories.apt import groups as apt_groups
from tests.accounts import error_code
from tests.repositories.apt.conftest import (
    REMOTE,
    create,
    mirror_files,
    mirror_key,
    paragraph,
    upload,
)
from tests.repositories.apt.packages import control_text, make_deb

GROUP = "/repository/apt-public"
OURS = "pool/main/m/megooarti-hello/megooarti-hello_1.0-1_all.deb"


def verified(signed: bytes, public_key: bytes) -> bytes:
    """What a clear signature vouches for, checked with one public key. Raises if not."""
    certificate = pysequoia.Cert.from_bytes(public_key)
    return pysequoia.verify(bytes=signed, store=lambda _: [certificate]).bytes


def names(packages: bytes) -> list[tuple[str, str]]:
    found = []
    for part in packages.decode().split("\n\n"):
        if part.strip():
            said = control.parse(part)
            found.append((control.get(said, "Package"), control.get(said, "Filename")))
    return found


MIRRORED = paragraph("hello", "2.10-5") + paragraph("libc6", "2.41-6")


@pytest.fixture
def mirror(fake_remote):
    """A mirror whose trixie has two packages for amd64, signed by its key."""
    fake_remote.files.update(mirror_files("trixie", {"main/binary-amd64": MIRRORED}))
    fake_remote.files["debian/pool/main/h/hello/hello_2.10-5_amd64.deb"] = b"hello from the mirror"
    return fake_remote


async def a_proxy(db, keys: str | None = None):
    return await create(
        db,
        "apt-debian",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
        format_config={"remote_keys": mirror_key().public_key if keys is None else keys},
    )


async def a_group(db, *members: str):
    return await create(db, "apt-public", type="group", group={"members": list(members)})


async def test_a_suite_one_member_has_is_its_release_signed_again_with_the_groups_key(
    client, db, root, mirror
):
    await create(db, "apt-hosted")
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    key = (await client.get(f"{GROUP}/public.key", headers=root)).content
    ours = (await client.get(f"{GROUP}/dists/stable/InRelease", headers=root)).content
    theirs = (await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)).content
    hosted = (await client.get("/repository/apt-hosted/dists/stable/Release", headers=root)).content

    assert verified(ours, key) + b"\n" == hosted
    mirrored = verified(
        mirror.files["debian/dists/trixie/InRelease"], mirror_key().public_key.encode()
    )
    assert verified(theirs, key) == mirrored


async def test_every_other_file_of_such_a_suite_comes_from_that_member(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    theirs = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.xz", headers=root)
    ours = await client.get(f"{GROUP}/dists/stable/main/binary-amd64/Packages", headers=root)
    hashed = await client.get(
        f"{GROUP}/dists/trixie/main/binary-amd64/by-hash/SHA256/{'a' * 64}", headers=root
    )

    assert theirs.content == mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"]
    assert names(ours.content) == [("megooarti-hello", OURS)]
    assert hashed.status_code == 404  # asked of the mirror, which has no such file
    assert "/debian/dists/trixie/main/binary-amd64/by-hash/SHA256/" + "a" * 64 in mirror.paths()


async def test_a_package_comes_from_the_first_member_that_has_it(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    ours = await client.get(f"{GROUP}/{OURS}", headers=root)
    theirs = await client.get(f"{GROUP}/pool/main/h/hello/hello_2.10-5_amd64.deb", headers=root)

    assert ours.content == make_deb()
    assert theirs.content == b"hello from the mirror"


async def test_a_suite_several_members_have_is_merged_and_an_earlier_members_package_wins(
    client, db, root, mirror
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())
    await upload(
        client,
        root,
        make_deb(control_text(package="libc6", version="2.41-6", architecture="amd64")),
    )

    key = (await client.get(f"{GROUP}/public.key", headers=root)).content
    release = verified(
        (await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)).content, key
    )
    packed = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)
    plain = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages", headers=root)

    assert release.startswith(b"Origin: MegooArti\nLabel: apt-public\nSuite: trixie\n")
    assert names(gzip.decompress(packed.content)) == [
        ("libc6", "pool/main/libc/libc6/libc6_2.41-6_amd64.deb"),
        ("megooarti-hello", OURS),
        ("hello", "pool/main/h/hello/hello_2.10-5_amd64.deb"),
    ]
    listed = releases.parse(release + b"\n").entries
    text = gzip.decompress(packed.content)
    # The text is named, as apt needs, and not kept.
    assert (
        listed["main/binary-amd64/Packages"].size,
        listed["main/binary-amd64/Packages"].sha256,
    ) == (
        len(text),
        hashlib.sha256(text).hexdigest(),
    )
    assert (
        listed["main/binary-amd64/Packages.gz"].size,
        listed["main/binary-amd64/Packages.gz"].sha256,
    ) == (
        len(packed.content),
        hashlib.sha256(packed.content).hexdigest(),
    )
    assert plain.status_code == 404


async def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_and_says_why(
    db, admin_client, mirror
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db, keys=other_key())
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(admin_client, {}, make_deb())

    packed = await admin_client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz")
    shown = (await admin_client.get("/api/v1/repositories/apt-debian")).json()

    assert names(gzip.decompress(packed.content)) == [("megooarti-hello", OURS)]
    assert shown["status"]["last_error"].startswith(
        "Left out of the group apt-public: its InRelease is not signed by its remote's keys"
    )


def other_key() -> str:
    from megooarti.repositories import signing

    return signing.generate_openpgp("Not the mirror").public_key


async def test_a_suite_only_a_member_that_was_left_out_has_is_not_found(client, db, root, mirror):
    await a_proxy(db, keys=other_key())
    await a_group(db, "apt-debian")

    response = await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)

    assert response.status_code == 404


async def test_a_packages_file_that_is_not_the_one_its_release_names_is_left_out(
    client, db, root, mirror
):
    mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"] = lzma.compress(
        paragraph("evil", "1.0")
    )
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    packed = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)

    assert names(gzip.decompress(packed.content)) == [("megooarti-hello", OURS)]


async def test_a_suite_is_written_once_until_a_member_changes(
    client, db, root, mirror, monkeypatch
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    written = []
    merged = apt_groups._merged

    async def counted(*arguments):
        written.append(1)
        return await merged(*arguments)

    monkeypatch.setattr(apt_groups, "_merged", counted)

    await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)
    await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)
    assert len(written) == 1
    await upload(client, root, make_deb())
    await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)
    assert len(written) == 2


async def test_a_suite_no_member_has_is_not_found(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_group(db, "apt-hosted")

    assert (await client.get(f"{GROUP}/dists/bookworm/InRelease", headers=root)).status_code == 404


async def test_the_group_signs_with_a_key_of_its_own(admin_client, db, mirror):
    await create(db, "apt-hosted")
    await a_group(db, "apt-hosted")

    groups = (await admin_client.get("/api/v1/repositories/apt-public/signing-key")).json()
    hosted = (await admin_client.get("/api/v1/repositories/apt-hosted/signing-key")).json()

    assert groups["fingerprint"] != hosted["fingerprint"]
    assert (await admin_client.get(f"{GROUP}/public.key")).text == groups["public_key"]


async def test_a_proxy_without_its_remotes_keys_cannot_be_a_member(admin_client):
    for body in (
        {"name": "apt-hosted", "format": "apt", "type": "hosted"},
        {
            "name": "apt-debian",
            "format": "apt",
            "type": "proxy",
            "proxy": {"remote_url": "http://deb.debian.org/debian"},
        },
    ):
        assert (await admin_client.post("/api/v1/repositories", json=body)).status_code == 201

    refused = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apt-public",
            "format": "apt",
            "type": "group",
            "group": {"members": ["apt-hosted", "apt-debian"]},
        },
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "group.members"


async def test_a_proxys_remote_keys_are_kept_and_shown(admin_client):
    keys = mirror_key().public_key

    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apt-debian",
            "format": "apt",
            "type": "proxy",
            "proxy": {"remote_url": "http://deb.debian.org/debian"},
            "format_config": {"remote_keys": keys},
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["format_config"] == {"remote_keys": keys}


async def test_a_group_takes_no_upload(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_group(db, "apt-hosted")

    response = await upload(client, root, make_deb(), repository="apt-public")

    assert response.status_code == 405
```

Change `backend/tests/repositories/apt/test_hosted.py`:

```diff
@@ -352,8 +352,9 @@ async def test_a_suite_is_chosen_when_the_repository_is_made_and_kept(admin_clie
         ("hosted", {"suite": "a/b"}, "format_config.suite"),
         ("hosted", {"suite": ""}, "format_config.suite"),
         ("hosted", {"component": "main"}, "format_config.component"),
-        ("proxy", {"suite": "stable"}, "format_config"),
-        ("group", {}, "type"),
+        ("proxy", {"suite": "stable"}, "format_config.suite"),
+        ("proxy", {"remote_keys": "not a key"}, "format_config.remote_keys"),
+        ("group", {"suite": "stable"}, "format_config"),
     ],
 )
 async def test_settings_that_cannot_be_used_are_refused(admin_client, type, format_config, field):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/apt -q`
Expected: 1 error during collection: there is no `megooarti.repositories.apt.groups`.

- [ ] **Step 3: Write the code and the guide**

Create `backend/src/megooarti/repositories/apt/groups.py`:

```python
"""Groups of APT repositories: one address, one key, for the suites of all the members.

A group serves each suite its members have. A client trusts the group's key and
nothing else, so the group checks what it signs: a proxy member's `InRelease` must be
signed by one of the keys its remote was given (`remote_keys`), and each `Packages`
file of it that the group reads must have the SHA-256 that `Release` names. A member
that fails a check is left out, its reason logged and kept as its last error, and the
group answers with the others. A hosted member's indexes are the server's own.

A suite that one member has is that member's, as it is: the group signs its `Release`
again, unchanged, and sends every other file of the suite on from that member, which
the client checks against that `Release`. Where several members have a suite, the
group writes a `Release` of its own: a component and architecture that one member has
is that member's files, and one that several have is one `Packages` written from
theirs, in their order, a package an earlier member has left out of a later one's.

What a group writes of a suite is kept, by a digest of what its members' indexes are
now: a hosted member's revision, and a proxy's `InRelease` and keys. Anything else is
answered as any group answers it: by the first member that has it.
"""

import asyncio
import gzip
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived, group, proxy, proxy_state, signing
from megooarti.repositories.apt import format as apt
from megooarti.repositories.apt import merge, releases
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve

log = structlog.get_logger(__name__)

# The most of a member's `InRelease`, and of a packed `Packages` file, that is read.
RELEASE_MOST = 16 * 1024 * 1024
PACKED_MOST = 256 * 1024 * 1024
# Which of a member's `Packages` files is read, the first that its `Release` names.
_VARIANTS = ("Packages.xz", "Packages.gz", "Packages")
_SIGNED = ("Release", "InRelease", "Release.gpg")


class LeftOut(Exception):
    """A member that a check found wanting, and why."""


@dataclass(frozen=True)
class Offer:
    """What one member has of a suite."""

    member: RepositoryContext
    release: releases.Release
    files: derived.Files | None  # a hosted member's own index files; None for a proxy


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def remote_keys(member: RepositoryContext) -> str:
    return member.repository.config.get("format_config", {}).get("remote_keys") or ""


async def _token(member: RepositoryContext, suite: str) -> str | None:
    """What a member's indexes of a suite are now, or None if it does not have the suite."""
    if member.repository.type == "hosted":
        if apt.suite_of(member) != suite:
            return None
        revision, _ = await member.revision()
        return f"{member.repository.id}:{revision}"
    path = f"dists/{suite}/InRelease"
    try:
        await proxy.ensure_cached(member, path)
    except ApiError as error:
        if error.status_code in group.TRY_NEXT:
            return None  # it does not have the suite, or cannot be asked now
        raise
    stored = await member.stat(path)
    if stored is None:
        return None
    keys = hashlib.sha256(remote_keys(member).encode()).hexdigest()
    return f"{member.repository.id}:{stored.sha256}:{keys}"


async def _leave_out(context: RepositoryContext, member: RepositoryContext, reason: str) -> None:
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


async def _offer(member: RepositoryContext, suite: str) -> Offer:
    """What a member has of a suite, checked. Raises LeftOut."""
    if member.repository.type == "hosted":
        written = await apt.hosted_indexes(member)
        return Offer(member, releases.parse(written.files["Release"]), written.files)
    keys = remote_keys(member)
    if not keys:
        raise LeftOut("it has no keys of its remote to check its InRelease with")
    try:
        signed = await member.read(f"dists/{suite}/InRelease", limit=RELEASE_MOST)
    except TooLarge:
        raise LeftOut("its InRelease is larger than this server reads") from None
    if signed is None:
        raise LeftOut("its InRelease is gone")
    try:
        text = signing.verify_clear(signed, signing.read_public_keys(keys))
        return Offer(member, releases.parse(text), None)
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    except signing.Unverified as error:
        raise LeftOut(f"its InRelease is not signed by its remote's keys: {error}") from None
    except releases.InvalidRelease as error:
        raise LeftOut(f"its InRelease cannot be read: {error}") from None


def _variant(offer: Offer, directory: str) -> tuple[str, releases.Entry] | None:
    for name in _VARIANTS:
        entry = offer.release.entries.get(f"{directory}/{name}")
        if entry is not None:
            return f"{directory}/{name}", entry
    return None


async def _packages(offer: Offer, suite: str, directory: str) -> bytes:
    """A member's `Packages` of one component and architecture, as text, checked."""
    name, entry = _variant(offer, directory)
    if offer.files is not None:
        packed = offer.files.get(name)
    else:
        path = f"dists/{suite}/{name}"
        try:
            await proxy.ensure_cached(offer.member, path)
            packed = await offer.member.read(path, limit=PACKED_MOST)
        except TooLarge:
            raise LeftOut(f"its {name} is larger than this server reads") from None
        except ApiError as error:
            raise LeftOut(f"its {name} cannot be fetched: {error.message}") from None
    if packed is None or hashlib.sha256(packed).hexdigest() != entry.sha256:
        raise LeftOut(f"its {name} is not the one its Release names")
    try:
        return await asyncio.to_thread(merge.unpacked, name, packed)
    except merge.InvalidIndex as error:
        raise LeftOut(str(error)) from None


def _packed(texts: list[bytes]) -> tuple[bytes, releases.Entry]:
    """Members' `Packages` merged, as `Packages.gz`, and what `Release` says of the text.

    apt finds an index in `Release` by the name of its text (`Packages`), and checks
    the text it unpacks against it, as Debian's mirrors have it: the text is named and
    not kept. Debian's `main` for one architecture is 57 MB of text and 13 MB packed;
    packed with gzip it takes a second, with xz most of a minute.
    """
    text = merge.merged(texts)
    named = releases.Entry(len(text), hashlib.sha256(text).hexdigest())
    return gzip.compress(text, 6, mtime=0), named


def _signed(text: bytes, signer: signing.Signer) -> derived.Files:
    return {"Release": text, "InRelease": signer.clear(text), "Release.gpg": signer.detached(text)}


def _union(lists: Sequence[Sequence[str]]) -> list[str]:
    seen: list[str] = []
    for items in lists:
        seen.extend(item for item in items if item not in seen)
    return seen


async def _merged(
    context: RepositoryContext, offers: list[Offer], suite: str, signer: signing.Signer
) -> derived.Written:
    """A `Release` of the group's own, for a suite several members have."""
    components = _union([offer.release.components for offer in offers])
    architectures = [
        name for name in _union([offer.release.architectures for offer in offers]) if name != "all"
    ]
    entries: dict[str, releases.Entry] = {}
    files: derived.Files = {}
    routes: dict[str, uuid.UUID | None] = {"*": offers[0].member.repository.id}

    def copy(offer: Offer, prefix: str) -> None:
        for path, entry in offer.release.entries.items():
            if path.startswith(prefix) and path not in entries:
                entries[path] = entry

    for component in components:
        having = [offer for offer in offers if component in offer.release.components]
        routes[component] = having[0].member.repository.id
        for architecture in architectures:
            directory = f"{component}/binary-{architecture}"
            with_it = [offer for offer in having if _variant(offer, directory) is not None]
            if len(with_it) == 1:
                copy(with_it[0], f"{directory}/")
                routes[directory] = with_it[0].member.repository.id
            elif with_it:
                routes[directory] = None  # what is merged is the group's; nothing else is
                texts = []
                for offer in with_it:
                    try:
                        texts.append(await _packages(offer, suite, directory))
                    except LeftOut as error:
                        await _leave_out(context, offer.member, str(error))
                packed, named = await asyncio.to_thread(_packed, texts)
                files[f"{directory}/Packages.gz"] = packed
                entries[f"{directory}/Packages.gz"] = releases.Entry(
                    len(packed), hashlib.sha256(packed).hexdigest()
                )
                entries[f"{directory}/Packages"] = named
        # What else a component has (translations, and the like) is its first member's.
        for path in list(having[0].release.entries):
            if path.startswith(f"{component}/") and not path.startswith(f"{component}/binary-"):
                copy(having[0], path)
    for path in offers[0].release.entries:
        if "/" not in path:
            copy(offers[0], path)

    moments = [offer.release.moment for offer in offers if offer.release.moment is not None]
    moment = max(moments) if moments else utcnow()
    text = releases.compose(
        label=context.repository.name,
        suite=suite,
        moment=moment,
        components=components,
        architectures=architectures,
        entries=entries.items(),
    )
    return derived.Written("", moment, {**files, **_signed(text, signer)}, routes)


async def _suite_index(
    context: RepositoryContext, suite: str
) -> tuple[derived.Written, dict[uuid.UUID, RepositoryContext]]:
    """What the group has of a suite, and its members that answer for it."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, suite)
        if token is not None:
            candidates.append(member)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has this suite.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    revision = hashlib.sha256("\n".join([key.fingerprint, suite, *tokens]).encode()).hexdigest()

    async def write() -> derived.Written:
        offers = []
        for member in candidates:
            try:
                offers.append(await _offer(member, suite))
            except LeftOut as error:
                await _leave_out(context, member, str(error))
        if not offers:
            raise _not_found("No repository of this group that has this suite could be checked.")
        signer = signing.signer(context.settings, key)
        if len(offers) > 1:
            written = await _merged(context, offers, suite, signer)
        else:
            # One member's suite is that member's: its own Release, signed again.
            signed = _signed(offers[0].release.text, signer)
            moment = offers[0].release.moment or utcnow()
            written = derived.Written("", moment, signed, {"*": offers[0].member.repository.id})
        return derived.Written(revision, written.changed, written.files, written.routes)

    written = await derived.written((context.repository.id, suite), revision, write)
    return written, {member.repository.id: member for member in members}


def _route(routes: dict[str, uuid.UUID | None], path: str) -> uuid.UUID | None:
    """The member that answers for a file of a suite, or None if none does."""
    parts = path.split("/")
    for prefix in ("/".join(parts[:2]), parts[0]):
        if prefix in routes:
            return routes[prefix]
    return routes.get("*")


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """A suite's index files from what the group writes; anything else from a member."""
    if request.method not in ("GET", "HEAD") or not path.startswith("dists/"):
        return await group.handle_group(context, request, path, serve)
    suite, _, under = path.removeprefix("dists/").partition("/")
    written, members = await _suite_index(context, suite)
    data = written.files.get(under)
    if data is not None:
        filename = under.rpartition("/")[2]
        return context.respond_with(
            data,
            request,
            filename=filename,
            content_type=apt.index_content_type(filename),
            last_modified=written.changed,
            etag=hashlib.sha256(data).hexdigest(),
            dated=False,
        )
    if under in _SIGNED:
        raise _not_found("No such file.")
    member = members.get(_route(written.routes, under))
    if member is None:
        raise _not_found("No repository of this group has this file.")
    return await serve(member, request, path)
```

Change `backend/src/megooarti/repositories/apt/format.py`:

```diff
@@ -30,6 +30,7 @@ from megooarti.repositories.content import RepositoryContext, Snapshot
 from megooarti.repositories.formats import (
     ComponentKey,
     Format,
+    Serve,
     Usage,
     declared_hashes,
     declared_size,
@@ -38,6 +39,7 @@ from megooarti.repositories.formats import (
     register,
 )
 from megooarti.repositories.forms import UploadForm
+from megooarti.repositories.models import Repository
 from megooarti.storage.backends import StagedBlob
 
 # Where what a package said of itself is kept among its file's attributes, and what is
@@ -86,7 +88,7 @@ def _invalid_setting(field: str, message: str) -> ApiError:
     return ApiError(422, "validation_error", "The request is not valid.", details)
 
 
-def _suite(context: RepositoryContext) -> str:
+def suite_of(context: RepositoryContext) -> str:
     return context.repository.config.get("format_config", {}).get("suite", DEFAULT_SUITE)
 
 
@@ -190,7 +192,7 @@ def _written(snapshot: Snapshot, suite: str, label: str, signer: signing.Signer)
     return derived.Written(snapshot.revision, snapshot.changed, {**files, **signed})
 
 
-async def _indexes(context: RepositoryContext) -> derived.Written:
+async def hosted_indexes(context: RepositoryContext) -> derived.Written:
     """The index files of this repository's revision: kept, or written now, once."""
     revision, _ = await context.revision()
 
@@ -200,20 +202,20 @@ async def _indexes(context: RepositoryContext) -> derived.Written:
         signer = signing.signer(context.settings, key)
         await context.release()  # writing them needs no connection
         return await asyncio.to_thread(
-            _written, snapshot, _suite(context), context.repository.name, signer
+            _written, snapshot, suite_of(context), context.repository.name, signer
         )
 
     return await derived.written(context.repository.id, revision, write)
 
 
-def _content_type(filename: str) -> str:
+def index_content_type(filename: str) -> str:
     if filename == "Release.gpg":
         return _SIGNATURE
     return _COMPRESSED.get(filename[filename.rfind(".") :], _TEXT) if "." in filename else _TEXT
 
 
 async def _index(context: RepositoryContext, request: Request, parsed: paths.AptPath) -> Response:
-    if parsed.suite != _suite(context) or (
+    if parsed.suite != suite_of(context) or (
         parsed.component and parsed.component != paths.COMPONENT
     ):
         raise _not_found("This repository has no such suite or component.")
@@ -221,7 +223,7 @@ async def _index(context: RepositoryContext, request: Request, parsed: paths.Apt
         name = parsed.filename
     else:
         name = f"{parsed.component}/binary-{parsed.architecture}/{parsed.filename}"
-    written = await _indexes(context)
+    written = await hosted_indexes(context)
     data = written.files.get(name)
     if data is None:
         raise _not_found("This repository has no packages of that architecture.")
@@ -229,7 +231,7 @@ async def _index(context: RepositoryContext, request: Request, parsed: paths.Apt
         data,
         request,
         filename=parsed.filename,
-        content_type=_content_type(parsed.filename),
+        content_type=index_content_type(parsed.filename),
         last_modified=written.changed,
         etag=hashlib.sha256(data).hexdigest(),
         # Two revisions can be made within one second: only the bytes say which one a
@@ -250,16 +252,35 @@ async def _public_key(context: RepositoryContext, request: Request) -> Response:
     )
 
 
+def _remote_keys(config: dict[str, Any]) -> dict[str, Any]:
+    """A proxy's settings: its remote's public keys, which a group checks it with."""
+    unknown = sorted(set(config) - {"remote_keys"})
+    if unknown:
+        raise _invalid_setting(f"format_config.{unknown[0]}", "This is not a setting of APT.")
+    keys = config.get("remote_keys") or ""
+    if not isinstance(keys, str):
+        raise _invalid_setting("format_config.remote_keys", "The keys are armoured text.")
+    if not keys.strip():
+        return {}
+    try:
+        signing.read_public_keys(keys)
+    except signing.KeysUnusable as error:
+        raise _invalid_setting("format_config.remote_keys", str(error)) from None
+    return {"remote_keys": keys}
+
+
 class AptFormat(Format):
     name = "apt"
-    types = frozenset({"hosted", "proxy"})
+    types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
     signs = signing.OPENPGP
 
     def validate_config(
         self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
     ) -> dict[str, Any]:
-        """A hosted repository's suite, which never changes. A proxy has no settings."""
+        """A hosted repository's suite, which never changes; a proxy's remote's keys."""
+        if repository_type == "proxy":
+            return _remote_keys(config)
         if repository_type != "hosted":
             return super().validate_config(repository_type, config, current)
         unknown = sorted(set(config) - {"suite"})
@@ -278,6 +299,15 @@ class AptFormat(Format):
             )
         return {"suite": suite}
 
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
@@ -330,7 +360,7 @@ class AptFormat(Format):
         if parsed.kind == "pool":
             return _DEB
         if parsed.kind in ("release", "packages"):
-            return _content_type(parsed.filename)
+            return index_content_type(parsed.filename)
         return declared
 
     def is_metadata(self, path: str) -> bool:
@@ -361,5 +391,15 @@ class AptFormat(Format):
             return await _index(context, request, parsed)
         raise _not_found()
 
+    async def handle_group(
+        self, context: RepositoryContext, request: Request, path: str, serve: Serve
+    ) -> Response:
+        if paths.classify(path).kind == "key" and _is_read(request):
+            return await _public_key(context, request)
+        # Imported here: it is written against this module.
+        from megooarti.repositories.apt import groups
+
+        return await groups.handle_group(context, request, path, serve)
+
 
 register(AptFormat())
```

Change `docs/formats/apt.md`:

````diff
@@ -46,6 +46,61 @@ echo "deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://rep
 For Ubuntu, the remote is `http://archive.ubuntu.com/ubuntu` and the keyring
 `/usr/share/keyrings/ubuntu-archive-keyring.gpg`.
 
+## Groups
+
+A group puts your own repositories and the mirrors behind one address, and signs
+everything it serves with a key of its own: a machine needs that one key, and nothing
+else. The group checks for it what apt would have checked, so a proxy can be a member
+only if it has its remote's public keys, armoured. For Debian's, on a machine that has
+the keyring and GnuPG:
+
+```bash
+keys=$(gpg --no-default-keyring --keyring /usr/share/keyrings/debian-archive-keyring.gpg \
+  --export --armor)
+jq -n --arg keys "$keys" '{
+  name: "apt-debian", format: "apt", type: "proxy",
+  proxy: {remote_url: "http://deb.debian.org/debian"},
+  format_config: {remote_keys: $keys}
+}' | curl -u admin -H 'Content-Type: application/json' -d @- \
+  http://localhost:8000/api/v1/repositories
+
+curl -u admin -H 'Content-Type: application/json' -d '{
+  "name": "apt-public", "format": "apt", "type": "group",
+  "group": {"members": ["apt-hosted", "apt-debian"]}
+}' http://localhost:8000/api/v1/repositories
+```
+
+On each machine, the group's key and a line for each suite:
+
+```bash
+curl -fsS -u ci -o /etc/apt/keyrings/apt-public.asc \
+  https://repo.example.com/repository/apt-public/public.key
+cat > /etc/apt/sources.list.d/megooarti.list <<'EOF'
+deb [signed-by=/etc/apt/keyrings/apt-public.asc] https://repo.example.com/repository/apt-public stable main
+deb [signed-by=/etc/apt/keyrings/apt-public.asc] https://repo.example.com/repository/apt-public trixie main
+EOF
+```
+
+- **A suite one member has is that member's.** The group signs its `Release` again,
+  unchanged, and passes every other file of the suite on from it; apt checks each
+  against that `Release`, as it would have checked it against the mirror's.
+- **A suite several members have** (a hosted repository whose suite is `trixie`,
+  beside a proxy of Debian; or `stable`, which Debian's mirrors have as well, as a
+  name for the current release) gets a `Release` of the group's own. A component and
+  architecture one member has is that member's files; one that several have is one
+  `Packages.gz` written from theirs, in the order of the members, a package
+  (the same name, version and architecture) that an earlier member has left out of a
+  later one's. That is written again whenever a member's indexes change, and takes
+  seconds for a component as large as Debian's `main`.
+- **A member is checked before it is used**: a proxy's `InRelease` must be signed by
+  one of its `remote_keys`, and each `Packages` file the group reads must be the one
+  that `Release` names. A member that fails is left out, the group answers with the
+  others, and the proxy's page says why as its last error. A proxy whose remote has no
+  `InRelease` is left out as well.
+- **Packages** are asked of the members in order, as in any group.
+- **The group's key** is made the first time it is needed, and is at
+  `/repository/<group>/public.key`, as a hosted repository's is.
+
 - **Credentials** go in a file of `/etc/apt/auth.conf.d/`, as above: a user name and a
   password, or a user name and an API token. apt sends them over HTTPS to the host a
   `machine` line names; over plain HTTP only if the line says so
@@ -84,11 +139,14 @@ For Ubuntu, the remote is `http://archive.ubuntu.com/ubuntu` and the keyring
 - **A proxy**'s remote is a mirror's root. What is under `dists/` is checked again with
   the remote after `metadata_max_age_minutes`; packages, and files under a `by-hash/`
   directory, never change and are kept.
-- Groups of APT repositories are not available yet.
+- **A proxy's `remote_keys`**, its remote's public keys, armoured, are what a group
+  it is a member of checks it with; a proxy that is not in a group does not use them,
+  and apt checks the mirror's signatures itself.
 
 ## Clients
 
 Tested with apt on Debian 13 and Ubuntu 26.04: a package built with `dpkg-deb`,
 uploaded and installed from a hosted repository; a repository signed with a key apt
-was not given, refused; and a package from each distribution's mirror, installed
-through a proxy.
+was not given, refused; a package from each distribution's mirror, installed through
+a proxy; and, on Debian, both through a group, with a suite of each member and with a
+suite they share, and a member signed by a key it was not given left out.
````

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/apt tests/test_documents.py -q`
Expected: 327 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests docs/formats/apt.md
git commit -m "feat: APT groups, one key for a suite of each member and for a suite they share"
```

---

### Task 5: apt through groups

**Files:**
- Modify: `backend/tests/test_apt_client.py`

**Interfaces:**
- Consumes: the stack, and Task 4.
- Produces: nothing other tasks use.

- [ ] **Step 1: The tests**

`with_apt` takes several suites; `build()` and `key_of()` are helpers for the new fixtures; `keyed` runs the guide's commands (GnuPG and jq in `debian:13`, which fetches them from Debian's mirror) against the stack.

Change `backend/tests/test_apt_client.py`:

```diff
@@ -46,12 +46,15 @@ dpkg-deb --root-owner-group --build p "/out/$1_$2_all.deb"
 """
 
 # Sets apt up to reach nothing but one repository of the stack, as `ci`.
-# `with_apt <keyring> <repository> <suite>`
+# `with_apt <keyring> <repository> <suite> [<suite> ...]`
 SETUP = f"""
 with_apt() {{
   rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*
-  echo "deb [signed-by=$1] http://gateway/repository/$2 $3 main" \\
-    > /etc/apt/sources.list.d/megooarti.list
+  keyring=$1 repository=$2
+  shift 2
+  for suite in "$@"; do
+    echo "deb [signed-by=$keyring] http://gateway/repository/$repository $suite main"
+  done > /etc/apt/sources.list.d/megooarti.list
   auth=/etc/apt/auth.conf.d/megooarti.conf
   printf 'machine http://gateway\\nlogin {USERNAME}\\npassword {PASSWORD}\\n' > $auth
   chmod 600 $auth
@@ -139,10 +142,8 @@ def repositories(administrator) -> None:
         assert status == 201, answer
 
 
-@pytest.fixture(scope="module")
-def published(repositories, tmp_path_factory) -> Path:
-    """Our package, built with dpkg-deb and uploaded. Returns where its public key is."""
-    work = tmp_path_factory.mktemp("apt")
+def build(work: Path, package: str, version: str) -> bytes:
+    """A package of our own, built with dpkg-deb in Debian's image."""
     (work / "build.sh").write_text(BUILD, encoding="utf-8", newline="\n")
     built = subprocess.run(
         [
@@ -156,17 +157,29 @@ def published(repositories, tmp_path_factory) -> Path:
             IMAGES["debian"],
             "sh",
             "/out/build.sh",
-            PACKAGE,
-            "1.0",
+            package,
+            version,
         ],
         capture_output=True,
         text=True,
         check=False,
     )
     assert built.returncode == 0, said(built)
-    package = (work / f"{PACKAGE}_1.0_all.deb").read_bytes()
+    return (work / f"{package}_{version}_all.deb").read_bytes()
+
+
+def key_of(repository: str, work: Path) -> None:
+    """Save a repository's public key where a client finds it, as `<repository>.asc`."""
+    status, key = send("GET", f"{repository}/public.key")
+    assert status == 200
+    (work / f"{repository}.asc").write_bytes(key)
 
-    status, answer = send("PUT", f"{HOSTED}/", package)
+
+@pytest.fixture(scope="module")
+def published(repositories, tmp_path_factory) -> Path:
+    """Our package, built with dpkg-deb and uploaded. Returns where its public key is."""
+    work = tmp_path_factory.mktemp("apt")
+    status, answer = send("PUT", f"{HOSTED}/", build(work, PACKAGE, "1.0"))
     assert status == 201, answer
     status, key = send("GET", f"{HOSTED}/public.key")
     assert status == 200
@@ -210,3 +223,126 @@ def test_apt_installs_a_public_package_through_a_proxy_of_its_mirror(published,
 
     assert installed.returncode == 0, said(installed)
     assert installed.stdout.splitlines()[-1] == "Hello, world!"
+
+
+# --- Groups ---------------------------------------------------------------------------
+
+ADMIN = "admin:'a brand new password'"  # what the `administrator` fixture made it
+SHARED = "megooarti-shared"
+# The guide's commands, as an administrator types them, against the stack: a proxy of
+# Debian with Debian's keys, armoured by GnuPG.
+GUIDE = f"""
+set -e
+apt-get update -qq && apt-get install -y -qq gpg jq curl > /dev/null
+keys=$(gpg --no-default-keyring --keyring /usr/share/keyrings/debian-archive-keyring.gpg \\
+  --export --armor)
+jq -n --arg keys "$keys" '{{
+  name: "apt-debian-keyed", format: "apt", type: "proxy",
+  proxy: {{remote_url: "http://deb.debian.org/debian", auto_block: false}},
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
+def keyed(published, administrator) -> None:
+    """A proxy of Debian made with the guide's commands, with Debian's keys."""
+    result = subprocess.run(
+        ["docker", "run", "--rm", "--network", NETWORK, IMAGES["debian"], "sh", "-c", GUIDE],
+        capture_output=True,
+        text=True,
+        encoding="utf-8",
+        errors="replace",
+        timeout=900,
+        check=False,
+    )
+    assert result.stdout.strip().endswith("made"), said(result)
+
+
+@pytest.fixture(scope="module")
+def groups(keyed, published, administrator) -> Path:
+    """Three groups, with their keys saved beside the hosted repository's.
+
+    `apt-public`: the hosted repository (suite stable) and the proxy: `trixie` is Debian's
+    alone, and `stable`, which Debian's mirror has as well, is both members'.
+    `apt-merged`: a hosted repository whose suite is trixie too, and the proxy.
+    `apt-wrong`: that one, and a proxy of Debian given a key Debian does not sign with.
+    """
+    made(
+        administrator,
+        {
+            "name": "apt-trixie",
+            "format": "apt",
+            "type": "hosted",
+            "format_config": {"suite": "trixie"},
+        },
+    )
+    status, answer = send("PUT", "apt-trixie/", build(published, SHARED, "1.0"))
+    assert status == 201, answer
+    _, _, hosted_key = call("GET", "/repositories/apt-hosted/signing-key", headers=administrator)
+    made(
+        administrator,
+        {
+            "name": "apt-debian-wrong",
+            "format": "apt",
+            "type": "proxy",
+            "proxy": {"remote_url": MIRRORS["debian"], "auto_block": False},
+            # A key Debian does not sign with: the hosted repository's own.
+            "format_config": {"remote_keys": hosted_key["public_key"]},
+        },
+    )
+    for name, members in (
+        ("apt-public", [HOSTED, "apt-debian-keyed"]),
+        ("apt-merged", ["apt-trixie", "apt-debian-keyed"]),
+        ("apt-wrong", ["apt-trixie", "apt-debian-wrong"]),
+    ):
+        made(
+            administrator,
+            {"name": name, "format": "apt", "type": "group", "group": {"members": members}},
+        )
+        key_of(name, published)
+    return published
+
+
+def test_apt_installs_from_a_suite_one_member_has_and_one_both_have_through_a_group(groups):
+    installed = apt(
+        "debian",
+        groups,
+        "with_apt /src/apt-public.asc apt-public stable trixie"
+        f" && apt-get update && apt-get install -y {PACKAGE} hello && {PACKAGE} && hello",
+    )
+
+    assert installed.returncode == 0, said(installed)
+    assert installed.stdout.splitlines()[-2:] == [f"hello from {PACKAGE} 1.0", "Hello, world!"]
+
+
+def test_apt_installs_from_a_suite_the_members_share_through_a_group(groups):
+    installed = apt(
+        "debian",
+        groups,
+        "with_apt /src/apt-merged.asc apt-merged trixie"
+        f" && apt-get update && apt-get install -y {SHARED} hello && {SHARED} && hello",
+    )
+
+    assert installed.returncode == 0, said(installed)
+    assert installed.stdout.splitlines()[-2:] == [f"hello from {SHARED} 1.0", "Hello, world!"]
+
+
+def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_of_a_group(groups, administrator):
+    installed = apt(
+        "debian",
+        groups,
+        "with_apt /src/apt-wrong.asc apt-wrong trixie && apt-get update"
+        f" && apt-get install -y {SHARED} && {SHARED} && ! apt-get install -y hello",
+    )
+    _, _, shown = call("GET", "/repositories/apt-debian-wrong", headers=administrator)
+
+    assert installed.returncode == 0, said(installed)
+    assert shown["status"]["last_error"].startswith("Left out of the group apt-wrong")
```

- [ ] **Step 2: Run them**

Run (in `backend/`): `uv run pytest -m docker tests/test_apt_client.py -q`
Expected: 9 passed. Through `apt-public`, apt installs our package from `stable` and Debian's `hello` from `trixie`; through `apt-merged`, both from `trixie`, whose `main` for amd64 the group merges from Debian's 69,908 packages and ours; through `apt-wrong`, ours, while `hello` is not found and `apt-debian-wrong` says why.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_apt_client.py
git commit -m "test: apt through groups, with a suite of each member, a suite they share, and a member left out"
```

---

### Task 6: The spec, and everything once more

**Files:**
- Modify: `docs/superpowers/specs/2026-10-14-linux-package-formats-design.md`

- [ ] **Step 1: The spec**

Change `docs/superpowers/specs/2026-10-14-linux-package-formats-design.md`:

```diff
@@ -127,6 +127,19 @@ What the server derives from the packages, it does not store (as Maven's metadat
 | P11 | `amd64` and `arm64` are always listed, beside the architectures of the packages. | One upload for `arm64` took `binary-amd64` away, and with it every package for `all` architectures from every amd64 machine. |
 | P12 | A snapshot is one statement, which sees the database at one moment: no retry, and no `503 repository_busy`. The index files of a revision are written once, however many requests want them at once (the others wait for that one), and in a task of their own, which a request that goes away does not stop. What is kept is the newest revision of each repository, at most 256 MiB of all of them, the least recently used going first. | On 30,000 packages, ten requests after a change each wrote the index again (19 to 29 seconds each, 1.5 GiB), every revision stayed in memory, and a busy repository could answer `503` to every try. |
 
+### Settled while building plan 12b
+
+| # | What | Why |
+| --- | --- | --- |
+| Q1 | A suite that one member of a group has is that member's, as it is: the group signs that member's `Release` again, unchanged, and every other file of the suite, `by-hash/` paths included, is sent on from that member. Only a suite several members have gets a `Release` of the group's own (5.4), with `Acquire-By-Hash: no`. | apt checks every file against the `Release` it was given, and that one was checked against the remote's keys. Writing Debian's indexes again would cost seconds and memory for no gain, and the mirror's translations and `by-hash/` files would be lost. |
+| Q2 | Where several members have a component and architecture, the group keeps `Packages.gz` alone; its `Release` names that and the text (`Packages`), which is not kept, with a `SHA256` list only. | Debian's `main` for amd64 is 57 MB of text and 13 MB packed: merged and packed with gzip in 2.4 seconds on the reference laptop, where xz would take most of a minute and keeping the text 57 MB of memory. apt finds an index by its text's name, and checks what it unpacks against it: without that line it did not fetch the merged index at all, as Task 5's first run showed. |
+| Q3 | A merged suite does not list the architecture `all`. | Debian and Ubuntu list a package for all architectures in each architecture's `Packages` (`No-Support-for-Architecture-all: Packages`), as a hosted repository does. |
+| Q4 | What a group writes of a suite is kept in the cache of 12a by the group and the suite, and by a digest of the group's key and its members' state: a hosted member's revision, a proxy member's `InRelease` and `remote_keys`. | It is written again only when one of these changes. The cache takes a digest as a revision: a different one takes the place of the last. |
+| Q5 | `Format.validate_member` refuses, when a group's members are set, a proxy without `remote_keys`. A proxy whose keys are taken away later is left out when the group is asked. A member left out says why as its last error (`Left out of the group <name>: ...`), which a proxy's next success with its remote clears. | 4.5, and a group that keeps answering when a member stops being checkable. |
+| Q6 | A proxy member whose remote has no `InRelease` is left out. A member whose `Packages` file fails its check is left out of that component and architecture only. | Debian, Ubuntu and their mirrors all have `InRelease`; checking `Release` against `Release.gpg` as well can come when a remote needs it. |
+| Q7 | A group's members are its leaves: a group within a group gives the group its own members, not its signed indexes. | One check of each remote, by the group a client trusts. |
+| Q8 | `remote_keys` is armoured text, of one or more keys, at most 1 MiB, and holds no private key. The guide makes it with `gpg --export --armor` from the distribution's keyring. | Debian's keyring is binary; a JSON field is text. |
+
 ## 5. APT
 
 ### 5.1 Layout
@@ -253,7 +266,7 @@ For each directory, the group merges the members' `APKINDEX` (the same name, ver
 | apk-tools 3 reads the index or the packages differently from apk-tools 2, or the newest Alpine writes packages in the newer format. | Plan 12d's tests on the two newest releases. If packages in the newer format are what `abuild` writes, reading them becomes part of plan 12d. |
 | A Python library for OpenPGP that signs as apt and dnf verify. | Settled for apt (P1): `pysequoia`. Plan 12c's tests show dnf verifying it too. |
 | `zstd` packages need `zstandard` (Python 3.13 has no `zstd` of its own). | A dependency, added in plan 12a. |
-| Merging a proxy's whole index (Debian's `Packages` is tens of megabytes) costs memory and time on the first request after a change. | The merged index is cached (4.5), and plan 12b measures a merge of Debian's `main` for `amd64`. |
+| Merging a proxy's whole index (Debian's `Packages` is tens of megabytes) costs memory and time on the first request after a change. | Measured in plan 12b (Q2): Debian's `main` for amd64, 69,908 packages, merged and packed in 2.4 seconds, 13 MB kept; a suite one member has is not merged at all (Q1). |
 | A YUM group passes on one member's `modules`: modular packages of the other members may be filtered by dnf. | Plan 12c's tests with Rocky's AppStream; the guide says what a group of modular repositories does. |
 | Keys sealed with the secret key are lost with it. | The backup guide already says to keep the secret key; it will name signing keys too. |
 
```

- [ ] **Step 2: Everything, once more**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: no finding, and 3260 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: no finding, 785 passed in 26 files, `Compiled successfully`. Nothing of the frontend changes.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 52 passed: the 49 there were, and the 3 of Task 5.

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: what plan 12b settled"
```
