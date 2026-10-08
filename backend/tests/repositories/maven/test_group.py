import hashlib

import pytest
import structlog

from megooarti.repositories import service
from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.metadata import Metadata, Plugin
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

APP = "com/acme/app"
LISTING = f"/repository/public/{APP}/maven-metadata.xml"
REMOTE_LISTING = f"maven2/{APP}/maven-metadata.xml"
SNAPSHOT_DIR = f"{APP}/1.0-SNAPSHOT"


@pytest.fixture
async def public(db, releases, snapshots, central):
    """The hosted `releases` and `snapshots` and the proxy `central`, in that order."""
    members = {"members": ["releases", "snapshots", "central"]}
    return await create(db, "public", type="group", group=members)


def remote_listing(*versions: str) -> bytes:
    """What a remote holds. Its own `latest` and `release` are deliberately wrong."""
    held = Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=versions,
        latest=versions[0],
        release=versions[0],
        last_updated="20200101000000",
    )
    return metadata.serialise(held)


async def put(client, root, path: str, content: bytes = b"x") -> None:
    response = await client.put(f"/repository/{path}", content=content, headers=root)
    assert response.status_code in (201, 204), response.text


async def release(client, root, version: str) -> None:
    await put(client, root, f"releases/{APP}/{version}/app-{version}.jar")


async def listing(client, headers, url: str = LISTING) -> Metadata:
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return metadata.parse(response.content)


async def test_metadata_is_merged_from_every_member(client, root, public, fake_remote):
    await release(client, root, "1.0")
    await release(client, root, "1.10")
    await put(client, root, f"snapshots/{APP}/2.1-SNAPSHOT/app-2.1-20261008.101500-1.jar")
    fake_remote.files[REMOTE_LISTING] = remote_listing("0.9", "2.0", "1.0", "1.9")

    document = await listing(client, root)

    assert (document.group_id, document.artifact_id) == ("com.acme", "app")
    assert document.versions == ("0.9", "1.0", "1.9", "1.10", "2.0", "2.1-SNAPSHOT")
    assert (document.latest, document.release) == ("2.1-SNAPSHOT", "2.0")
    assert document.last_updated > "20200101000000"


async def test_group_metadata_is_answered_like_any_file(client, root, public, fake_remote):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")
    first = await client.get(LISTING, headers=root)
    etag = first.headers["ETag"]

    headed = await client.head(LISTING, headers=root)
    unchanged = await client.get(LISTING, headers={**root, "If-None-Match": etag})

    assert metadata.parse(first.content).versions == ("1.0", "2.0")
    assert first.headers["Content-Type"] == "application/xml"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["Content-Disposition"].startswith(
        'attachment; filename="maven-metadata.xml"'
    )
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Content-Length"] == str(len(first.content))
    assert (unchanged.status_code, unchanged.content) == (304, b"")


async def test_the_checksum_of_group_metadata_is_of_the_merged_document(
    client, root, public, fake_remote
):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")

    document = await client.get(LISTING, headers=root)
    sha1 = await client.get(f"{LISTING}.sha1", headers=root)
    md5 = await client.head(f"{LISTING}.md5", headers=root)

    assert metadata.parse(document.content).versions == ("1.0", "2.0")
    assert sha1.text == hashlib.sha1(document.content).hexdigest()
    assert sha1.headers["Content-Type"] == "text/plain"
    assert (md5.status_code, md5.headers["Content-Length"]) == (200, "32")
    assert fake_remote.paths() == [f"/{REMOTE_LISTING}"]  # never the remote's checksum file


async def test_metadata_no_member_has_is_not_found(client, root, public, fake_remote):
    document = await client.get(LISTING, headers=root)
    checksum = await client.get(f"{LISTING}.sha1", headers=root)

    assert (document.status_code, error_code(document)) == (404, "not_found")
    assert checksum.status_code == 404


async def test_a_member_whose_remote_is_down_is_left_out(client, root, public, fake_remote):
    await release(client, root, "1.0")
    await put(client, root, f"snapshots/{APP}/2.1-SNAPSHOT/app-2.1-SNAPSHOT.jar")
    fake_remote.down = True

    document = await listing(client, root)

    assert document.versions == ("1.0", "2.1-SNAPSHOT")


async def test_a_group_whose_only_source_is_down_has_nothing(client, root, public, fake_remote):
    fake_remote.down = True

    response = await client.get(LISTING, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


@pytest.mark.parametrize(
    "held",
    [
        b"this is not xml",
        b'<!DOCTYPE metadata [<!ENTITY a "b">]><metadata><groupId>&a;</groupId></metadata>',
        b"<metadata>" + b"<a>" * 500 + b"</a>" * 500 + b"</metadata>",
        b"<metadata>" + b" " * (4 * 1024 * 1024) + b"</metadata>",
    ],
    ids=["not-xml", "doctype", "deeply-nested", "over-4-mib"],
)
async def test_a_member_document_that_cannot_be_used_is_left_out_and_logged(
    client, root, public, fake_remote, held
):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = held

    with structlog.testing.capture_logs() as logs:
        document = await listing(client, root)

    assert document.versions == ("1.0",)
    unusable = [entry for entry in logs if entry["event"] == "member_metadata_unusable"]
    assert [(entry["repository"], entry["path"]) for entry in unusable] == [
        ("central", f"{APP}/maven-metadata.xml")
    ]


async def test_an_offline_member_is_left_out(client, root, public, fake_remote, db):
    await release(client, root, "1.0")
    await put(client, root, f"snapshots/{APP}/2.1-SNAPSHOT/app-2.1-SNAPSHOT.jar")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")
    snapshots = await service.get_repository(db, "snapshots")
    await service.update_repository(
        db, snapshots, online=False, format_config={"version_policy": "snapshot"}
    )
    await db.commit()

    document = await listing(client, root)

    assert document.versions == ("1.0", "2.0")  # the others, merged, without `snapshots`


async def test_snapshot_metadata_comes_through_a_group(client, root, public, fake_remote):
    for name in ("app-1.0-20261008.101500-1.jar", "app-1.0-20261008.111500-2.jar"):
        await put(client, root, f"snapshots/{SNAPSHOT_DIR}/{name}")

    document = await listing(client, root, f"/repository/public/{SNAPSHOT_DIR}/maven-metadata.xml")

    assert document.version == "1.0-SNAPSHOT"
    assert (document.snapshot_timestamp, document.snapshot_build) == ("20261008.111500", 2)
    assert [entry.value for entry in document.snapshot_versions] == ["1.0-20261008.111500-2"]
    assert fake_remote.paths() == []  # `central` takes releases only, so it is not asked


async def test_files_and_their_checksums_come_from_the_member_that_has_them(
    client, root, public, fake_remote
):
    ours, theirs = b"PK deployed here", b"PK held by the remote"
    await put(client, root, f"releases/{APP}/1.0/app-1.0.jar", ours)
    fake_remote.files["maven2/com/acme/lib/3.0/lib-3.0.jar"] = theirs
    hosted = f"/repository/public/{APP}/1.0/app-1.0.jar"
    proxied = "/repository/public/com/acme/lib/3.0/lib-3.0.jar"

    hosted_sha1 = await client.get(f"{hosted}.sha1", headers=root)
    proxied_sha1 = await client.get(f"{proxied}.sha1", headers=root)
    proxied_file = await client.get(proxied, headers=root)

    assert (await client.get(hosted, headers=root)).content == ours
    assert hosted_sha1.text == hashlib.sha1(ours).hexdigest()
    assert proxied_sha1.text == hashlib.sha1(theirs).hexdigest()
    assert proxied_file.content == theirs
    assert fake_remote.paths() == ["/maven2/com/acme/lib/3.0/lib-3.0.jar"]


async def test_plugins_are_merged_and_the_earlier_member_wins_a_prefix(
    client, root, public, fake_remote
):
    ours = Plugin("Ours", "acme", "acme-maven-plugin")
    await put(client, root, "releases/com/acme/acme-maven-plugin/1.0/acme-maven-plugin-1.0.jar")
    await put(
        client,
        root,
        "releases/com/acme/maven-metadata.xml",
        metadata.serialise(Metadata(plugins=(ours,))),
    )
    theirs = (Plugin("Theirs", "acme", "their-plugin"), Plugin("Other", "other", "other-plugin"))
    fake_remote.files["maven2/com/acme/maven-metadata.xml"] = metadata.serialise(
        Metadata(plugins=theirs)
    )

    document = await listing(client, root, "/repository/public/com/acme/maven-metadata.xml")

    assert document.plugins == (ours, Plugin("Other", "other", "other-plugin"))


async def test_a_group_inside_a_group_contributes_its_merged_document(
    client, root, public, fake_remote, db
):
    await create(db, "extra")
    await create(db, "outer", type="group", group={"members": ["extra", "public"]})
    await release(client, root, "1.0")
    await put(client, root, f"extra/{APP}/3.0/app-3.0.jar")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")

    document = await listing(client, root, f"/repository/outer/{APP}/maven-metadata.xml")

    assert document.versions == ("1.0", "2.0", "3.0")


async def test_reading_through_the_group_needs_read_on_the_group_only(
    client, root, public, fake_remote, make_user, db
):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")
    members = ["repository:maven:releases:read", "repository:maven:central:read"]
    await roles.create_role(db, "group-readers", "", ["repository:maven:public:read"], [])
    await roles.create_role(db, "member-readers", "", members, [])
    await db.commit()
    await make_user("gina", roles=["group-readers"])
    await make_user("mel", roles=["member-readers"])

    by_group_reader = await listing(client, basic("gina", PASSWORD))
    by_member_reader = await client.get(LISTING, headers=basic("mel", PASSWORD))
    by_nobody = await client.get(LISTING)

    assert by_group_reader.versions == ("1.0", "2.0")
    assert (by_member_reader.status_code, error_code(by_member_reader)) == (403, "forbidden")
    assert by_nobody.status_code == 401


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
@pytest.mark.parametrize("suffix", ["", ".sha1"])
async def test_group_metadata_cannot_be_written(client, root, public, method, suffix):
    response = await client.request(method, f"{LISTING}{suffix}", content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
