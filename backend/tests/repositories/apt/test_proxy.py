"""A proxy of a Debian mirror: its indexes are asked about again, its packages kept."""

import pytest

from megooarti.repositories.apt.format import AptFormat
from tests.repositories.apt.conftest import REMOTE, create
from tests.repositories.apt.packages import make_deb

PROXY = "/repository/debian"
SIGNED = b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\nOrigin: Debian\n-----BEGIN PGP"
PACKAGE = "pool/main/g/glibc/libc6_2.41-6_amd64.deb"
BY_HASH = "dists/trixie/main/binary-amd64/by-hash/SHA256/0123abcd"


@pytest.fixture
async def debian(db):
    """A proxy that asks its remote about an index every time it is asked for one."""
    return await create(
        db,
        "debian",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
    )


@pytest.fixture
def remote(fake_remote, debian):
    fake_remote.files["debian/dists/trixie/InRelease"] = SIGNED
    fake_remote.files[f"debian/{PACKAGE}"] = make_deb()
    fake_remote.files[f"debian/{BY_HASH}"] = b"Package: libc6\n"
    return fake_remote


@pytest.mark.parametrize(
    ("path", "metadata"),
    [
        ("dists/trixie/InRelease", True),
        ("dists/trixie/main/binary-amd64/Packages.xz", True),
        ("dists/trixie/main/i18n/Translation-en.bz2", True),
        (BY_HASH, False),
        (PACKAGE, False),
    ],
)
def test_a_suites_indexes_are_metadata_and_what_a_hash_names_is_not(path, metadata):
    assert AptFormat().is_metadata(path) is metadata


async def test_the_mirrors_signed_index_is_passed_on_as_it_signed_it(client, root, remote):
    first = await client.get(f"{PROXY}/dists/trixie/InRelease", headers=root)
    second = await client.get(f"{PROXY}/dists/trixie/InRelease", headers=root)

    assert first.content == second.content == SIGNED
    assert first.headers["content-type"] == "text/plain; charset=utf-8"
    assert remote.paths().count("/debian/dists/trixie/InRelease") == 2  # asked again


async def test_a_package_and_what_a_hash_names_are_fetched_once(client, root, remote):
    for _ in range(2):
        package = await client.get(f"{PROXY}/{PACKAGE}", headers=root)
        named = await client.get(f"{PROXY}/{BY_HASH}", headers=root)

    assert package.content == make_deb()
    assert package.headers["content-type"] == "application/vnd.debian.binary-package"
    assert named.content == b"Package: libc6\n"
    assert remote.paths().count(f"/debian/{PACKAGE}") == 1
    assert remote.paths().count(f"/debian/{BY_HASH}") == 1


async def test_a_cached_package_is_a_component_by_its_file_name(client, root, remote):
    await client.get(f"{PROXY}/{PACKAGE}", headers=root)

    found = await client.get("/api/v1/content/debian/components", headers=root)

    assert [(c["name"], c["version"]) for c in found.json()["items"]] == [("libc6", "2.41-6")]


async def test_a_proxy_takes_no_package(client, root, remote):
    response = await client.put(f"{PROXY}/", content=make_deb(), headers=root)

    assert response.status_code == 405
