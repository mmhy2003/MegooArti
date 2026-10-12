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


async def test_staged_content_is_read_into_memory_only_up_to_a_limit(files, context_for):
    context = await context_for(files, None)
    staged = await context.stage_bytes(b"small")

    assert await context.read_staged(staged, limit=5) == b"small"
    assert await context.read_staged(staged, limit=4) is None
    await context.discard(staged)
