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
