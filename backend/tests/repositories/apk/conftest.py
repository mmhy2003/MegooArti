"""apk repositories made for a test, what uploads to them, and a mirror to proxy."""

import asyncio
import functools

import pytest

from megooarti.repositories import derived, service, signing
from megooarti.repositories.apk import index, packages
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic
from tests.repositories.apk.packages import pieces

URL = "/repository/apk-hosted"
MAIN = f"{URL}/v3.24/main"
REMOTE = "http://remote.test/alpine"
KEY = "megooarti-apk-hosted.rsa.pub"


async def create(
    db,
    name: str = "apk-hosted",
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
    format_config: dict | None = None,
) -> Repository:
    """An apk repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="apk",
        type=type,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        group=group,
        format_config=format_config or {},
    )
    await db.commit()
    return repository


_GENERATE = signing.generate_rsa


@functools.cache
def rsa_key() -> signing.Material:
    """One RSA key for every test: making one of 4096 bits takes a second."""
    return _GENERATE()


@pytest.fixture(autouse=True)
def quick_keys(monkeypatch):
    """Every repository's key is made at once, and is the same."""
    monkeypatch.setattr(signing, "generate_rsa", rsa_key)


async def written_behind() -> None:
    """Wait for what a group writes behind its requests, as the next request would find it.

    In the tests every session shares one connection, which two cannot use at once.
    """
    while derived._writing:
        await asyncio.gather(*list(derived._writing.values()), return_exceptions=True)


@pytest.fixture(autouse=True)
def nothing_kept():
    """Every test writes its indexes anew: what one wrote is not served to the next."""
    derived.forget()
    yield
    derived.forget()


@pytest.fixture
async def hosted(db) -> Repository:
    return await create(db)


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def upload(client, headers, path: str, package: bytes, *, repository: str = "apk-hosted"):
    """A package sent as `curl --upload-file` sends it to its path."""
    return await client.put(f"/repository/{repository}/{path}", content=package, headers=headers)


# --- A mirror, as a proxy's remote --------------------------------------------------

ROOT = REMOTE.removeprefix("http://remote.test/")
MIRROR_KEY = "alpine-devel@lists.alpinelinux.org-test.rsa.pub"


@functools.cache
def mirror_key() -> signing.Material:
    """The key the stand-in mirror signs with, made once for every test."""
    return _GENERATE()


async def mirror_files(
    directory: str,
    packages_by_name: dict[str, bytes],
    *,
    key: signing.Material | None = None,
    root: str = ROOT,
) -> dict[str, bytes]:
    """A mirror's directory, as the stand-in remote serves it, by path under its host:
    the packages, by their file names, and their index, signed with `key`."""
    listed = [
        index.Listed(len(data), await packages.read(pieces(data)))
        for data in packages_by_name.values()
    ]
    signer = signing.RsaSigner((key or mirror_key()).private_key)
    architecture = directory.rpartition("/")[2]
    data = index.index_file(listed, architecture, "v3.24.2", MIRROR_KEY, signer, 1792000000)
    files = {f"{root}/{directory}/{index.INDEX}": data}
    files.update(
        {f"{root}/{directory}/{name}": package for name, package in packages_by_name.items()}
    )
    return files
