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
    unfilled, skipping = 0, False
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
                    elif len(form.files) + unfilled >= MAX_FILES:
                        raise InvalidForm(f"it has more than {MAX_FILES} files")
                    elif not event.filename:
                        # A file input nobody filled in: counted, read past, never staged.
                        unfilled, skipping = unfilled + 1, True
                    else:
                        receiving = _Receiving(name, event.filename, stage)
                elif event.kind == "data":
                    if skipping:
                        continue
                    if receiving is not None:
                        await receiving.add(event.data)
                    else:
                        value += event.data
                        if len(value) > FIELD_LIMIT:
                            raise InvalidForm(f"{name} is longer than {FIELD_LIMIT} bytes")
                elif skipping:
                    skipping = False
                elif receiving is not None:
                    uploaded, receiving = await receiving.done(), None
                    form.files.append(uploaded)
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
