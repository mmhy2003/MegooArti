"""A proxy of a Fedora mirror: its `repomd.xml` is asked about again, the rest kept."""

import pytest

from megooarti.repositories.yum.format import YumFormat
from tests.repositories.yum.conftest import REMOTE, create
from tests.repositories.yum.packages import make_rpm

PROXY = "/repository/fedora"
REPOMD = b'<?xml version="1.0" encoding="UTF-8"?>\n<repomd xmlns="http://linux.duke.edu/metadata/repo"/>\n'
PRIMARY = "repodata/0123456789abcdef0123456789abcdef-primary.xml.zst"
PACKAGE = "Packages/b/bash-5.3.9-3.fc44.x86_64.rpm"
REMOTE_PATH = REMOTE.removeprefix("http://remote.test/")


@pytest.fixture
async def fedora(db):
    """A proxy that asks its remote about `repomd.xml` every time it is asked for it."""
    return await create(
        db,
        "fedora",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
    )


@pytest.fixture
def remote(fake_remote, fedora):
    fake_remote.files[f"{REMOTE_PATH}/repodata/repomd.xml"] = REPOMD
    fake_remote.files[f"{REMOTE_PATH}/{PRIMARY}"] = b"packed primary"
    fake_remote.files[f"{REMOTE_PATH}/{PACKAGE}"] = make_rpm("bash", "5.3.9", "3.fc44", "x86_64")
    return fake_remote


@pytest.mark.parametrize(
    ("path", "metadata"),
    [
        ("repodata/repomd.xml", True),
        ("repodata/repomd.xml.asc", True),
        ("repodata/primary.xml.gz", True),
        (PRIMARY, False),
        (PACKAGE, False),
    ],
)
def test_repomd_is_metadata_and_what_a_hash_names_is_not(path, metadata):
    assert YumFormat().is_metadata(path) is metadata


async def test_the_mirrors_repomd_is_passed_on_as_it_wrote_it(client, root, remote):
    first = await client.get(f"{PROXY}/repodata/repomd.xml", headers=root)
    second = await client.get(f"{PROXY}/repodata/repomd.xml", headers=root)

    assert first.content == second.content == REPOMD
    assert remote.paths().count(f"/{REMOTE_PATH}/repodata/repomd.xml") == 2  # asked again


async def test_a_package_and_what_a_hash_names_are_fetched_once(client, root, remote):
    for _ in range(2):
        package = await client.get(f"{PROXY}/{PACKAGE}", headers=root)
        named = await client.get(f"{PROXY}/{PRIMARY}", headers=root)

    assert package.headers["content-type"] == "application/x-rpm"
    assert named.content == b"packed primary"
    assert named.headers["content-type"] == "application/zstd"
    assert remote.paths().count(f"/{REMOTE_PATH}/{PACKAGE}") == 1
    assert remote.paths().count(f"/{REMOTE_PATH}/{PRIMARY}") == 1


async def test_a_cached_package_is_a_component_by_its_file_name(client, root, remote):
    await client.get(f"{PROXY}/{PACKAGE}", headers=root)
    await client.get(f"{PROXY}/{PRIMARY}", headers=root)

    found = await client.get("/api/v1/content/fedora/components", headers=root)

    assert [(c["name"], c["version"]) for c in found.json()["items"]] == [("bash", "5.3.9-3.fc44")]


async def test_a_proxy_takes_no_package(client, root, remote):
    response = await client.put(f"{PROXY}/a.rpm", content=make_rpm(), headers=root)

    assert response.status_code == 405
