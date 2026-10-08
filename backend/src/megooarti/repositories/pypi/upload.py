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
