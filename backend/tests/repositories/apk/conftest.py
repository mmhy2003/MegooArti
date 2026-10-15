"""apk repositories made for a test, and what uploads to them."""

import functools

import pytest

from megooarti.repositories import derived, service, signing
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

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
