import hashlib

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from tests.accounts import error_code
from tests.repositories.maven.conftest import REMOTE, create

JAR_PATH = "com/acme/app/1.0/app-1.0.jar"
JAR = f"/repository/central/{JAR_PATH}"
BYTES = b"PK\x03\x04 a jar the remote holds"
SHA1 = hashlib.sha1(BYTES).hexdigest()
LISTING_PATH = "com/acme/app/maven-metadata.xml"
LISTING = f"/repository/central/{LISTING_PATH}"
# Not how MegooArti would write it: a proxy passes metadata on untouched.
REMOTE_LISTING = (
    b"<metadata>\n\t<groupId>com.acme</groupId><artifactId>app</artifactId>\n"
    b"<versioning><release>1.0</release><versions><version>1.0</version></versions>"
    b"</versioning></metadata>"
)
SNAPSHOT_DIR = "/repository/central/com/acme/app/1.0-SNAPSHOT"


def asked(remote, method: str = "GET") -> list[str]:
    return [path.removeprefix("/maven2/") for path in remote.paths(method)]


@pytest.fixture
def remote(fake_remote, central):
    fake_remote.files[f"maven2/{JAR_PATH}"] = BYTES
    fake_remote.files[f"maven2/{LISTING_PATH}"] = REMOTE_LISTING
    return fake_remote


async def test_an_artifact_is_fetched_cached_and_given_its_component(client, root, remote, db):
    first = await client.get(JAR, headers=root)
    second = await client.get(JAR, headers=root)

    assert (first.status_code, first.content) == (200, BYTES)
    assert second.content == BYTES
    assert first.headers["Content-Type"] == "application/java-archive"
    assert asked(remote) == [JAR_PATH]
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("com.acme", "app", "1.0")


@pytest.mark.parametrize("algorithm", ["md5", "sha1", "sha256", "sha512"])
async def test_a_checksum_comes_from_the_cached_file(client, root, remote, algorithm):
    await client.get(JAR, headers=root)

    response = await client.get(f"{JAR}.{algorithm}", headers=root)

    assert (response.status_code, response.text) == (200, hashlib.new(algorithm, BYTES).hexdigest())
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert asked(remote) == [JAR_PATH]


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_checksum_asked_for_first_fetches_its_file_once(client, root, remote, db, method):
    checksum = await client.request(method, f"{JAR}.sha1", headers=root)
    file = await client.get(JAR, headers=root)

    assert checksum.status_code == 200
    assert checksum.headers["Content-Length"] == "40"
    assert checksum.headers["X-Checksum-Sha1"] == hashlib.sha1(SHA1.encode()).hexdigest()
    assert checksum.content in (b"", SHA1.encode())
    assert file.content == BYTES
    assert asked(remote) == [JAR_PATH]
    assert asked(remote, "HEAD") == []
    assert list(await db.scalars(select(Asset.path))) == [JAR_PATH]


async def test_a_checksum_of_what_the_remote_lacks_is_not_found(client, root, remote):
    url = "/repository/central/com/acme/app/9.9/app-9.9.jar.sha1"

    first = await client.get(url, headers=root)
    again = await client.get(url, headers=root)

    assert (first.status_code, error_code(first)) == (404, "not_found")
    assert again.status_code == 404
    assert asked(remote) == ["com/acme/app/9.9/app-9.9.jar"]  # remembered, not asked twice


async def test_a_checksum_cannot_be_made_while_the_remote_is_down(client, root, remote):
    remote.down = True

    response = await client.get(f"{JAR}.sha1", headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")


async def test_metadata_is_served_as_the_remote_wrote_it(client, root, remote):
    listing = await client.get(LISTING, headers=root)
    sha1 = await client.get(f"{LISTING}.sha1", headers=root)

    assert (listing.status_code, listing.content) == (200, REMOTE_LISTING)
    assert listing.headers["Content-Type"] == "application/xml"
    assert sha1.text == hashlib.sha1(REMOTE_LISTING).hexdigest()
    assert asked(remote) == [LISTING_PATH]


async def test_metadata_is_asked_about_again_and_releases_are_not(client, root, db, fake_remote):
    ages = {"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": -1}
    await create(db, "eager", type="proxy", proxy=ages)
    fake_remote.files[f"maven2/{JAR_PATH}"] = BYTES
    fake_remote.files[f"maven2/{LISTING_PATH}"] = REMOTE_LISTING

    for _ in range(2):
        await client.get(f"/repository/eager/{JAR_PATH}", headers=root)
        await client.get(f"/repository/eager/{LISTING_PATH}", headers=root)

    assert asked(fake_remote) == [JAR_PATH, LISTING_PATH, LISTING_PATH]


@pytest.mark.parametrize(
    "name", ["app-1.0-SNAPSHOT.jar", "app-1.0-SNAPSHOT.jar.sha1", "maven-metadata.xml"]
)
async def test_a_release_proxy_does_not_ask_for_snapshots(client, root, remote, name):
    remote.files[f"maven2/com/acme/app/1.0-SNAPSHOT/{name}"] = b"at the remote"

    fetched = await client.get(f"{SNAPSHOT_DIR}/{name}", headers=root)
    headed = await client.head(f"{SNAPSHOT_DIR}/{name}", headers=root)

    assert (fetched.status_code, error_code(fetched)) == (404, "not_found")
    assert headed.status_code == 404
    assert asked(remote) == asked(remote, "HEAD") == []


async def test_a_snapshot_proxy_fetches_snapshots(client, root, db, fake_remote):
    await create(
        db, "nightly", type="proxy", proxy={"remote_url": REMOTE}, version_policy="snapshot"
    )
    name = "com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-1.jar"
    fake_remote.files[f"maven2/{name}"] = BYTES

    snapshot = await client.get(f"/repository/nightly/{name}", headers=root)
    release = await client.get(f"/repository/nightly/{JAR_PATH}", headers=root)

    assert snapshot.content == BYTES
    assert release.status_code == 404
    assert asked(fake_remote) == [name]


async def test_a_strict_proxy_does_not_ask_for_paths_outside_the_layout(client, root, remote):
    remote.files["maven2/notes/readme.txt"] = b"hello"

    response = await client.get("/repository/central/notes/readme.txt", headers=root)
    checksum = await client.get("/repository/central/notes/readme.txt.md5", headers=root)

    assert (response.status_code, checksum.status_code) == (404, 404)
    assert asked(remote) == []


async def test_what_was_cached_while_permissive_is_still_served_once_strict(
    client, root, db, fake_remote
):
    loose = await create(
        db, "loose", type="proxy", proxy={"remote_url": REMOTE}, layout_policy="permissive"
    )
    fake_remote.files["maven2/notes/readme.txt"] = b"hello"
    fake_remote.files["maven2/notes/other.txt"] = b"never fetched"
    url = "/repository/loose/notes/readme.txt"
    assert (await client.get(url, headers=root)).content == b"hello"
    await service.update_repository(
        db,
        loose,
        online=True,
        proxy={"remote_url": REMOTE},
        format_config={"layout_policy": "strict"},
    )
    await db.commit()

    cached = await client.get(url, headers=root)
    checksum = await client.get(f"{url}.md5", headers=root)
    other = await client.get("/repository/loose/notes/other.txt", headers=root)

    assert cached.content == b"hello"
    assert checksum.text == hashlib.md5(b"hello").hexdigest()
    assert other.status_code == 404
    assert asked(fake_remote) == ["notes/readme.txt"]


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
@pytest.mark.parametrize("path", [JAR, f"{JAR}.sha1", LISTING])
async def test_a_maven_proxy_cannot_be_written_to(client, root, remote, method, path):
    response = await client.request(method, path, content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
    assert asked(remote) == []


@pytest.mark.parametrize("suffix", [".sha1.sha1", ".sha1.md5", ".md5.sha512"])
async def test_a_checksum_of_a_checksum_is_never_fetched(client, root, remote, db, suffix):
    remote.files[f"maven2/{JAR_PATH}.sha1"] = b"the remote's own checksum file"
    remote.files[f"maven2/{JAR_PATH}.md5"] = b"the remote's own checksum file"

    fetched = await client.get(f"{JAR}{suffix}", headers=root)
    headed = await client.head(f"{JAR}{suffix}", headers=root)

    assert (fetched.status_code, error_code(fetched)) == (404, "not_found")
    assert headed.status_code == 404
    assert asked(remote) == asked(remote, "HEAD") == []
    assert list(await db.scalars(select(Asset.path))) == []
