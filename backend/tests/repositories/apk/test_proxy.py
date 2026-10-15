"""A proxy of an Alpine mirror: its indexes are asked about again, its packages kept."""

import pytest

from megooarti.repositories.apk.format import ApkFormat
from tests.repositories.apk.conftest import REMOTE, create
from tests.repositories.apk.packages import DATA, REAL

PROXY = "/repository/alpine"
INDEX = "v3.24/main/x86_64/APKINDEX.tar.gz"
PACKAGE = f"v3.24/main/x86_64/{REAL[1]}"


@pytest.fixture
async def alpine(db):
    """A proxy that asks its remote about an index every time it is asked for one."""
    return await create(
        db,
        "alpine",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
    )


@pytest.fixture
def remote(fake_remote, alpine):
    fake_remote.files[f"alpine/{INDEX}"] = (DATA / "APKINDEX.tar.gz").read_bytes()
    fake_remote.files[f"alpine/{PACKAGE}"] = (DATA / REAL[1]).read_bytes()
    return fake_remote


@pytest.mark.parametrize(("path", "metadata"), [(INDEX, True), (PACKAGE, False)])
def test_an_index_is_metadata_and_a_package_is_not(path, metadata):
    assert ApkFormat().is_metadata(path) is metadata


async def test_the_mirrors_index_is_passed_on_as_it_signed_it(client, root, remote):
    first = await client.get(f"{PROXY}/{INDEX}", headers=root)
    second = await client.get(f"{PROXY}/{INDEX}", headers=root)

    assert first.content == second.content == (DATA / "APKINDEX.tar.gz").read_bytes()
    assert first.headers["content-type"] == "application/gzip"
    assert remote.paths().count(f"/alpine/{INDEX}") == 2  # asked again


async def test_a_package_is_fetched_once(client, root, remote):
    for _ in range(2):
        package = await client.get(f"{PROXY}/{PACKAGE}", headers=root)

    assert package.content == (DATA / REAL[1]).read_bytes()
    assert remote.paths().count(f"/alpine/{PACKAGE}") == 1


async def test_a_cached_package_is_a_component_by_its_file_name(client, root, remote):
    await client.get(f"{PROXY}/{PACKAGE}", headers=root)
    await client.get(f"{PROXY}/{INDEX}", headers=root)

    found = await client.get("/api/v1/content/alpine/components", headers=root)

    assert [(c["name"], c["version"]) for c in found.json()["items"]] == [("yash-binsh", "2.60-r0")]


async def test_a_proxy_takes_no_package(client, root, remote):
    response = await client.put(f"{PROXY}/{PACKAGE}", content=b"x", headers=root)

    assert response.status_code == 405
