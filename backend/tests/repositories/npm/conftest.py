import base64
import hashlib
import io
import json
import tarfile

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/npm"
REMOTE = "http://remote.test/registry"


async def create(
    db,
    name: str,
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
) -> Repository:
    """An npm repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="npm",
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


def tarball_of(package: str, version: str) -> bytes:
    """Stand-in tarball bytes, different for every package and version."""
    return f"\x1f\x8b tarball of {package}@{version}".encode()


def publish_body(package: str, version: str, *, tag: str = "latest", **manifest) -> dict:
    """What `npm publish` sends for one version."""
    data = tarball_of(package, version)
    dist = {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": f"http://client.example/{package}/-/{package}-{version}.tgz",
    }
    return {
        "_id": package,
        "name": package,
        "dist-tags": {tag: version},
        "versions": {version: {"name": package, "version": version, "dist": dist, **manifest}},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(data).decode(),
                "length": len(data),
            }
        },
    }


def address(package: str, repository: str = "npm") -> str:
    """A package's address as npm writes it: a scoped name has its slash encoded."""
    return f"/repository/{repository}/{package.replace('/', '%2f')}"


async def publish(client, headers, package: str, version: str, **changes):
    """Publish one version. Returns the response."""
    repository = changes.pop("repository", "npm")
    body = publish_body(package, version, **changes)
    return await client.put(address(package, repository), json=body, headers=headers)


def remote_document(package: str, *versions: str, remote: str = REMOTE, **extra) -> bytes:
    """A package document as a remote registry serves it, with its links at the remote."""
    name = package.rpartition("/")[2]
    listed = {
        version: {
            "name": package,
            "version": version,
            "dist": {
                "shasum": hashlib.sha1(tarball_of(package, version)).hexdigest(),
                "tarball": f"{remote}/{package}/-/{name}-{version}.tgz",
            },
        }
        for version in versions
    }
    document = {
        "_id": package,
        "name": package,
        "dist-tags": {"latest": versions[-1]},
        "versions": listed,
        "time": {version: "2020-01-01T00:00:00.000Z" for version in versions},
        **extra,
    }
    return json.dumps(document).encode()


@pytest.fixture
async def registry(db) -> Repository:
    return await create(db, "npm")


@pytest.fixture
async def npmjs(db) -> Repository:
    """A proxy of the fake remote."""
    return await create(db, "npmjs", type="proxy", proxy={"remote_url": REMOTE})


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


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
