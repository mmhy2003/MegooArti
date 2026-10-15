"""YUM repositories made for a test, what uploads to them, and a mirror to proxy."""

import asyncio
import functools
import hashlib

import pytest

from megooarti.repositories import derived, service, signing
from megooarti.repositories.models import Repository
from megooarti.repositories.yum import repodata, rpms
from tests.accounts import PASSWORD, basic
from tests.repositories.yum.packages import pieces

URL = "/repository/yum-hosted"
REMOTE = "http://remote.test/fedora/44/Everything/x86_64/os"


async def create(
    db,
    name: str = "yum-hosted",
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
    format_config: dict | None = None,
) -> Repository:
    """A YUM repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="yum",
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


async def written_behind() -> None:
    """Wait for what a group writes behind its requests, as the next request would find it.

    In the tests every session shares one connection, which two cannot use at once.
    """
    while derived._writing:
        await asyncio.gather(*list(derived._writing.values()), return_exceptions=True)


@pytest.fixture(autouse=True)
def nothing_kept():
    """Every test writes its metadata anew: what one wrote is not served to the next."""
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


async def upload(client, headers, path: str, package: bytes, *, repository: str = "yum-hosted"):
    """A package sent as `curl --upload-file` sends it to its path."""
    return await client.put(f"/repository/{repository}/{path}", content=package, headers=headers)


# --- A mirror, as a proxy's remote --------------------------------------------------

MIRRORED_AT = 1792000000
ROOT = REMOTE.removeprefix("http://remote.test/")
COMPS = b'<?xml version="1.0" encoding="UTF-8"?>\n<comps>the mirror\'s package groups</comps>\n'


@functools.cache
def mirror_key() -> signing.Material:
    """The key the stand-in mirror signs with, made once for every test."""
    return signing.generate_openpgp("A Fedora mirror")


async def mirror_files(
    packages: dict[str, bytes],
    *,
    root: str = ROOT,
    key: signing.Material | None = None,
    comps: bool = True,
) -> dict[str, bytes]:
    """A mirror's repository, as the stand-in remote serves it, by path under its host.

    `packages` are by their paths under the repository. Its `repomd.xml` names package
    groups too, if `comps`; it is signed, with `key`, if a key is given.
    """
    listed = []
    for path, data in packages.items():
        rpm = await rpms.read(pieces(data))
        sha256 = hashlib.sha256(data).hexdigest()
        listed.append(repodata.Listed(path, len(data), sha256, MIRRORED_AT, rpm))
    files = repodata.repodata(listed, MIRRORED_AT)
    if comps:
        digest = hashlib.sha256(COMPS).hexdigest()
        files[f"{digest}-comps.xml"] = COMPS
        element = (
            f'  <data type="group">\n    <checksum type="sha256">{digest}</checksum>\n'
            f'    <location href="repodata/{digest}-comps.xml"/>\n'
            f"    <timestamp>{MIRRORED_AT}</timestamp>\n    <size>{len(COMPS)}</size>\n"
            "  </data>\n"
        )
        files["repomd.xml"] = files["repomd.xml"].replace(
            b"</repomd>", element.encode() + b"</repomd>"
        )
    if key is not None:
        files["repomd.xml.asc"] = signing.Signer(key.private_key).detached(files["repomd.xml"])
    mirrored = {f"{root}/repodata/{name}": data for name, data in files.items()}
    mirrored.update({f"{root}/{path}": data for path, data in packages.items()})
    return mirrored
