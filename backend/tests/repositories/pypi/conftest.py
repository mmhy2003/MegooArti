import hashlib
from html.parser import HTMLParser

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/pypi"
BOUNDARY = "megooarti-test-boundary-7MA4YWxkTrZu0gW"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"
WHEEL = "megooarti_greeter-1.0.0-py3-none-any.whl"
SDIST = "megooarti_greeter-1.0.0.tar.gz"
# A remote index, and the other host it keeps its files on, as pypi.org does.
REMOTE = "http://remote.test/pypi"
FILES_HOST = "http://files.test"


async def create(
    db,
    name: str,
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
) -> Repository:
    """A PyPI repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="pypi",
        type=type,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        group=group,
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


def remote_link(
    filename: str, *attributes: str, at: str = FILES_HOST, data: bytes | None = None
) -> str:
    """A link as a remote index writes it, to a file kept at `<at>/packages/<file name>`.

    The hash is that of `content_of(filename)` unless `data` says what the remote holds.
    """
    digest = hashlib.sha256(content_of(filename) if data is None else data).hexdigest()
    written = "".join(f" {attribute}" for attribute in attributes)
    address = f"{at}/packages/{filename}#sha256={digest}"
    return f'<a href="{address}"{written}>{filename}</a><br />\n'


def remote_page(project: str, *links: str) -> bytes:
    """A project page as a remote index serves it. A plain file name is linked as it is."""
    written = "".join(link if "<" in link else remote_link(link) for link in links)
    head = f"<!DOCTYPE html>\n<html><head><title>Links for {project}</title></head>\n<body>\n"
    return f"{head}<h1>Links for {project}</h1>\n{written}</body></html>\n".encode()


class Anchors(HTMLParser):
    """The links of a page, as a browser or an installer would read them."""

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
    """The links of a page that was served: (attributes, text) for each."""
    parser = Anchors()
    parser.feed(response.text)
    return parser.found


def link_to(project: str, version: str, filename: str, **attributes) -> tuple[dict, str]:
    """What a served page says of a file whose content is `content_of(filename)`."""
    digest = hashlib.sha256(content_of(filename)).hexdigest()
    href = f"../../packages/{project}/{version}/{filename}#sha256={digest}"
    return {"href": href, **attributes}, filename


@pytest.fixture
async def index(db) -> Repository:
    return await create(db, "pypi")


@pytest.fixture
async def upstream(db) -> Repository:
    """A proxy of the fake remote index."""
    return await create(db, "upstream", type="proxy", proxy={"remote_url": REMOTE})


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
