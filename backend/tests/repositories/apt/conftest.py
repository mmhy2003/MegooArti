"""APT repositories made for a test, what uploads to them, and a mirror to proxy."""

import asyncio
import functools
import hashlib
import lzma
from datetime import UTC, datetime

import pytest

from megooarti.repositories import derived, service, signing
from megooarti.repositories.apt import indexes
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/apt-hosted"
REMOTE = "http://remote.test/debian"


async def create(
    db,
    name: str = "apt-hosted",
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
    format_config: dict | None = None,
) -> Repository:
    """An APT repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="apt",
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


async def upload(
    client, headers, package: bytes, *, repository: str = "apt-hosted", method: str = "PUT"
):
    """A package sent as `curl --upload-file` sends it."""
    return await client.request(
        method, f"/repository/{repository}/", content=package, headers=headers
    )


# --- A mirror, as a proxy's remote --------------------------------------------------


MIRRORED_AT = datetime(2026, 9, 12, 7, 55, 41, tzinfo=UTC)


@functools.cache
def mirror_key() -> signing.Material:
    """The key the stand-in mirror signs with, made once for every test."""
    return signing.generate_openpgp("A Debian mirror")


def mirror_files(
    suite: str,
    packages: dict[str, bytes],
    *,
    key: signing.Material | None = None,
    root: str = "debian",
    by_hash: bool = False,
    moment: datetime = MIRRORED_AT,
    valid_until: datetime | None = None,
) -> dict[str, bytes]:
    """A mirror's suite, as the stand-in remote serves it, by path under its host.

    `packages` are the text of each `Packages` file, by its directory under the suite
    (`main/binary-amd64`). Each is served as `Packages.xz`, and under `by-hash/` too
    if its `InRelease` says `Acquire-By-Hash: yes`. The `InRelease` says what Debian's
    says of itself.
    """
    files, lines = {}, []
    for directory, text in packages.items():
        packed = lzma.compress(text)
        digest = hashlib.sha256(packed).hexdigest()
        files[f"dists/{suite}/{directory}/Packages.xz"] = packed
        if by_hash:
            files[f"dists/{suite}/{directory}/by-hash/SHA256/{digest}"] = packed
        lines.append(f" {digest} {len(packed):>16} {directory}/Packages.xz")
    components = sorted({directory.split("/")[0] for directory in packages})
    architectures = sorted({directory.split("-")[-1] for directory in packages})
    head = [
        "Origin: Debian",
        "Label: Debian",
        f"Suite: {suite}",
        f"Codename: {suite}",
        "Version: 13.7",
        f"Date: {indexes.date(moment)}",
        *([f"Valid-Until: {indexes.date(valid_until)}"] if valid_until else []),
        f"Acquire-By-Hash: {'yes' if by_hash else 'no'}",
        f"Architectures: {' '.join(architectures)}",
        f"Components: {' '.join(components)}",
        "SHA256:",
    ]
    release = ("\n".join(head + lines) + "\n").encode()
    signer = signing.Signer((key or mirror_key()).private_key)
    files[f"dists/{suite}/InRelease"] = signer.clear(release)
    return {f"{root}/{path}": data for path, data in files.items()}


def paragraph(
    name: str, version: str, architecture: str = "amd64", file: str | None = None
) -> bytes:
    """A package as a mirror's `Packages` lists it."""
    filename = file or f"pool/main/{name[0]}/{name}/{name}_{version}_{architecture}.deb"
    return (
        f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n"
        f"Filename: {filename}\nSize: 1\nSHA256: {'0' * 64}\n"
        f"Description: {name} from the mirror\n\n"
    ).encode()
