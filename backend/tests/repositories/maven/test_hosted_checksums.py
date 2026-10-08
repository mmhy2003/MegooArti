import hashlib

import pytest
import structlog
from sqlalchemy import select

from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

JAR = "/repository/releases/com/acme/app/1.0/app-1.0.jar"
BYTES = b"PK\x03\x04 pretend this is a jar"
SHA1 = hashlib.sha1(BYTES).hexdigest()


@pytest.fixture
async def jar(client, releases, root) -> None:
    response = await client.put(JAR, content=BYTES, headers=root)
    assert response.status_code == 201


@pytest.mark.parametrize("algorithm", ["md5", "sha1", "sha256", "sha512"])
async def test_a_checksum_is_answered_from_the_stored_file(client, jar, root, algorithm):
    response = await client.get(f"{JAR}.{algorithm}", headers=root)
    file = await client.head(JAR, headers=root)

    assert (response.status_code, response.text) == (200, hashlib.new(algorithm, BYTES).hexdigest())
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Last-Modified"] == file.headers["Last-Modified"]
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"].startswith(
        f'attachment; filename="app-1.0.jar.{algorithm}"'
    )


async def test_a_checksum_supports_head(client, jar, root):
    response = await client.head(f"{JAR}.sha1", headers=root)

    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["Content-Length"] == "40"


async def test_a_checksum_of_nothing_is_not_found(client, releases, root):
    response = await client.get(f"{JAR}.sha1", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


@pytest.mark.parametrize(
    "body",
    [
        SHA1.encode(),
        f"{SHA1.upper()}  app-1.0.jar\n".encode(),
        f"SHA1(app-1.0.jar)= {SHA1}\n".encode(),
    ],
)
async def test_a_matching_checksum_is_accepted_and_not_stored(client, jar, root, db, body):
    response = await client.put(f"{JAR}.sha1", content=body, headers=root)

    assert (response.status_code, response.content) == (201, b"")
    assert list(await db.scalars(select(Asset.path))) == ["com/acme/app/1.0/app-1.0.jar"]


@pytest.mark.parametrize("body", [b"0" * 40, b"not a checksum", b"", b"a" * 2000])
async def test_a_wrong_checksum_fails_the_upload_and_leaves_the_file(client, jar, root, body):
    response = await client.put(f"{JAR}.sha1", content=body, headers=root)

    assert (response.status_code, error_code(response)) == (400, "checksum_mismatch")
    assert (await client.get(JAR, headers=root)).content == BYTES


async def test_a_wrong_checksum_is_logged_for_the_operator(client, jar, root):
    # Maven only warns when a checksum upload fails, so the log is where this shows.
    with structlog.testing.capture_logs() as logs:
        await client.put(f"{JAR}.sha1", content=b"0" * 40, headers=root)
        await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=root)

    mismatches = [entry for entry in logs if entry["event"] == "checksum_mismatch"]
    assert mismatches == [
        {
            "event": "checksum_mismatch",
            "log_level": "warning",
            "repository": "releases",
            "path": "com/acme/app/1.0/app-1.0.jar",
            "algorithm": "sha1",
            "by": "root",
        }
    ]


async def test_a_checksum_for_a_missing_file_is_not_found(client, releases, root):
    response = await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_a_checksum_cannot_be_deleted(client, jar, root):
    response = await client.delete(f"{JAR}.sha1", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, PUT"
    assert (await client.get(JAR, headers=root)).status_code == 200


async def test_a_checksum_follows_the_policies_of_its_file(client, releases, root):
    snapshot = await client.put(
        "/repository/releases/com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT.jar.sha1",
        content=SHA1.encode(),
        headers=root,
    )
    outside = await client.put(
        "/repository/releases/notes/readme.txt.md5", content=b"0" * 32, headers=root
    )

    assert (snapshot.status_code, error_code(snapshot)) == (400, "version_policy_violation")
    assert (outside.status_code, error_code(outside)) == (400, "invalid_path")


async def test_uploading_a_checksum_needs_permission_to_write(client, jar, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:maven:releases:read"], [])
    await roles.create_role(db, "adders", "", ["repository:maven:releases:add"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    await make_user("ada", roles=["adders"])
    reader, adder = basic("rae", PASSWORD), basic("ada", PASSWORD)

    by_reader = await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=reader)
    by_adder = await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=adder)
    by_nobody = await client.put(f"{JAR}.sha1", content=SHA1.encode())
    read_by_reader = await client.get(f"{JAR}.sha1", headers=reader)
    read_by_adder = await client.get(f"{JAR}.sha1", headers=adder)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert by_adder.status_code == 201
    assert by_nobody.status_code == 401
    assert read_by_reader.text == SHA1
    assert (read_by_adder.status_code, error_code(read_by_adder)) == (403, "forbidden")


async def test_a_read_only_repository_refuses_checksum_uploads(client, db, root):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await client.put(
        "/repository/frozen/com/acme/app/1.0/app-1.0.jar.sha1", content=SHA1.encode(), headers=root
    )

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")
