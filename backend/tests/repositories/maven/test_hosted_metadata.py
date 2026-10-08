import hashlib

from sqlalchemy import select

from megooarti.repositories.maven import metadata
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

APP = "releases/com/acme/app"
LISTING = f"/repository/{APP}/maven-metadata.xml"
SNAP = "snapshots/com/acme/app/1.0-SNAPSHOT"
CLIENT_MADE = (
    b"<metadata><groupId>com.acme</groupId><artifactId>app</artifactId>"
    b"<versioning><versions><version>9.9</version></versions></versioning></metadata>"
)


async def put(client, root, path: str, content: bytes = b"x") -> None:
    response = await client.put(f"/repository/{path}", content=content, headers=root)
    assert response.status_code in (201, 204), response.text


async def deploy(client, root, version: str) -> None:
    await put(client, root, f"{APP}/{version}/app-{version}.jar")
    await put(client, root, f"{APP}/{version}/app-{version}.pom")


async def listing(client, root, url: str = LISTING) -> metadata.Metadata:
    response = await client.get(url, headers=root)
    assert response.status_code == 200, response.text
    return metadata.parse(response.content)


async def test_artifact_metadata_is_generated_from_what_is_stored(client, releases, root):
    await deploy(client, root, "1.10")
    await deploy(client, root, "1.9")

    response = await client.get(LISTING, headers=root)

    document = metadata.parse(response.content)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/xml"
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert (document.group_id, document.artifact_id) == ("com.acme", "app")
    assert document.versions == ("1.9", "1.10")
    assert (document.latest, document.release) == ("1.10", "1.10")
    assert len(document.last_updated) == 14
    assert document.plugins == ()


async def test_metadata_for_nothing_is_not_found(client, releases, root):
    fetched = await client.get(LISTING, headers=root)
    headed = await client.head(LISTING, headers=root)

    assert (fetched.status_code, error_code(fetched)) == (404, "not_found")
    assert headed.status_code == 404


async def test_metadata_follows_a_delete(client, releases, root):
    await put(client, root, f"{APP}/1.0/app-1.0.jar")
    await put(client, root, f"{APP}/1.1/app-1.1.jar")

    await client.delete(f"/repository/{APP}/1.1/app-1.1.jar", headers=root)
    after_one = await listing(client, root)
    await client.delete(f"/repository/{APP}/1.0/app-1.0.jar", headers=root)
    after_both = await client.get(LISTING, headers=root)

    assert (after_one.versions, after_one.latest) == (("1.0",), "1.0")
    assert after_both.status_code == 404


async def test_metadata_supports_head_and_conditions(client, releases, root):
    await deploy(client, root, "1.0")
    first = await client.get(LISTING, headers=root)
    etag = first.headers["ETag"]

    headed = await client.head(LISTING, headers=root)
    unchanged = await client.get(LISTING, headers={**root, "If-None-Match": etag})
    await deploy(client, root, "1.1")
    changed = await client.get(LISTING, headers={**root, "If-None-Match": etag})

    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Content-Length"] == str(len(first.content))
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert changed.status_code == 200
    assert changed.headers["ETag"] != etag


async def test_uploaded_metadata_is_accepted_and_dropped(client, releases, root, db):
    await put(client, root, f"{APP}/1.0/app-1.0.jar")

    uploaded = await client.put(LISTING, content=CLIENT_MADE, headers=root)

    assert (uploaded.status_code, uploaded.content) == (201, b"")
    assert (await listing(client, root)).versions == ("1.0",)
    assert list(await db.scalars(select(Asset.path))) == ["com/acme/app/1.0/app-1.0.jar"]


async def test_uploaded_metadata_must_be_readable(client, releases, root):
    hostile = b'<!DOCTYPE metadata [<!ENTITY a "b">]><metadata><groupId>&a;</groupId></metadata>'

    for body in (b"not xml", hostile, b"<project/>"):
        response = await client.put(LISTING, content=body, headers=root)
        assert (response.status_code, error_code(response)) == (400, "invalid_metadata")


async def test_uploaded_metadata_has_a_size_limit(client, releases, root):
    huge = b"<metadata>" + b" " * (1024 * 1024) + b"</metadata>"

    response = await client.put(LISTING, content=huge, headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_metadata")


async def test_metadata_cannot_be_deleted(client, releases, root):
    await deploy(client, root, "1.0")

    response = await client.delete(LISTING, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, PUT"
    assert (await listing(client, root)).versions == ("1.0",)


async def test_the_checksum_of_metadata_is_of_the_document_served(client, releases, root):
    missing = await client.get(f"{LISTING}.sha1", headers=root)
    await deploy(client, root, "1.0")

    document = await client.get(LISTING, headers=root)
    sha1 = await client.get(f"{LISTING}.sha1", headers=root)
    md5 = await client.get(f"{LISTING}.md5", headers=root)

    assert missing.status_code == 404
    assert sha1.text == hashlib.sha1(document.content).hexdigest()
    assert md5.text == hashlib.md5(document.content).hexdigest()
    assert sha1.headers["Last-Modified"] == document.headers["Last-Modified"]


async def test_a_checksum_uploaded_for_metadata_is_accepted_unchecked(client, releases, root, db):
    before_any_file = await client.put(f"{LISTING}.sha1", content=b"0" * 40, headers=root)
    await deploy(client, root, "1.0")
    after = await client.put(f"{LISTING}.md5", content=b"0" * 32, headers=root)

    assert (before_any_file.status_code, after.status_code) == (201, 201)
    assert len(list(await db.scalars(select(Asset.path)))) == 2


async def test_dropped_uploads_need_permission_to_write(client, releases, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:maven:releases:read"], [])
    await roles.create_role(db, "adders", "", ["repository:maven:releases:add"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    await make_user("ada", roles=["adders"])
    reader, adder = basic("rae", PASSWORD), basic("ada", PASSWORD)

    for url in (LISTING, f"{LISTING}.sha1"):
        refused = await client.put(url, content=CLIENT_MADE, headers=reader)
        assert (refused.status_code, error_code(refused)) == (403, "forbidden"), url
        assert (await client.put(url, content=CLIENT_MADE)).status_code == 401, url

    assert (await client.put(LISTING, content=CLIENT_MADE, headers=adder)).status_code == 201
    assert (await client.put(f"{LISTING}.sha1", content=b"0", headers=adder)).status_code == 201


async def test_snapshot_metadata_points_at_the_latest_build(client, snapshots, root):
    for name in (
        "app-1.0-20261008.101500-1.jar",
        "app-1.0-20261008.101500-1.pom",
        "app-1.0-20261008.111500-2.jar",
        "app-1.0-20261008.111500-2.pom",
    ):
        await put(client, root, f"{SNAP}/{name}")

    version_level = await listing(client, root, f"/repository/{SNAP}/maven-metadata.xml")
    artifact_level = await listing(
        client, root, "/repository/snapshots/com/acme/app/maven-metadata.xml"
    )

    assert (version_level.group_id, version_level.artifact_id, version_level.version) == (
        "com.acme",
        "app",
        "1.0-SNAPSHOT",
    )
    assert (version_level.snapshot_timestamp, version_level.snapshot_build) == (
        "20261008.111500",
        2,
    )
    assert {(entry.extension, entry.value) for entry in version_level.snapshot_versions} == {
        ("jar", "1.0-20261008.111500-2"),
        ("pom", "1.0-20261008.111500-2"),
    }
    assert artifact_level.versions == ("1.0-SNAPSHOT",)
    assert (artifact_level.latest, artifact_level.release) == ("1.0-SNAPSHOT", "")


async def test_uploaded_snapshot_metadata_is_dropped_without_being_read(client, snapshots, root):
    url = f"/repository/{SNAP}/maven-metadata.xml"

    uploaded = await client.put(url, content=b"this is not xml at all", headers=root)

    assert uploaded.status_code == 201
    assert (await client.get(url, headers=root)).status_code == 404


async def test_a_release_repository_has_no_snapshot_metadata(client, releases, root):
    url = f"/repository/{APP}/1.0-SNAPSHOT/maven-metadata.xml"

    fetched = await client.get(url, headers=root)
    uploaded = await client.put(url, content=CLIENT_MADE, headers=root)

    assert fetched.status_code == 404
    assert (uploaded.status_code, error_code(uploaded)) == (400, "version_policy_violation")
