"""Uploading to a Maven repository through the content API leaves it as a deploy would."""

import hashlib

from tests.accounts import error_code
from tests.repositories.maven.conftest import create

UPLOAD = "/api/v1/content/releases/upload"
APP = {"group": "com.acme", "artifact": "app", "version": "1.0"}
HELD = "/repository/releases/com/acme/app"
JAR = b"PK\x03\x04 pretend this is a jar"


def parts(*files: tuple[str, str, bytes]) -> list:
    return [(field, (name, data)) for field, name, data in files]


async def send(client, root, fields: dict, *files: tuple[str, str, bytes], to: str = UPLOAD):
    return await client.post(to, data=fields, files=parts(*files), headers=root)


async def test_an_uploaded_artifact_is_there_for_a_build_to_use(client, releases, root):
    response = await send(client, root, APP, ("file", "build-output.jar", JAR))
    jar = await client.get(f"{HELD}/1.0/app-1.0.jar", headers=root)
    pom = await client.get(f"{HELD}/1.0/app-1.0.pom", headers=root)
    sha1 = await client.get(f"{HELD}/1.0/app-1.0.jar.sha1", headers=root)
    metadata = await client.get(f"{HELD}/maven-metadata.xml", headers=root)

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == [
        "com/acme/app/1.0/app-1.0.jar",
        "com/acme/app/1.0/app-1.0.pom",
    ]
    assert [(c["namespace"], c["name"], c["version"]) for c in stored["components"]] == [
        ("com.acme", "app", "1.0")
    ]
    assert (jar.content, jar.headers["Content-Type"]) == (JAR, "application/java-archive")
    assert "<artifactId>app</artifactId>" in pom.text and "<packaging>jar</packaging>" in pom.text
    assert pom.headers["Content-Type"] == "application/xml"
    assert sha1.text == hashlib.sha1(JAR).hexdigest()
    assert "<version>1.0</version>" in metadata.text


async def test_a_pom_that_is_sent_is_the_one_kept(client, releases, root):
    own = b"<project><modelVersion>4.0.0</modelVersion><name>Ours</name></project>"

    response = await send(
        client,
        root,
        APP,
        ("file", "app.jar", JAR),
        ("file.sources", "app-sources.jar", b"sources"),
        ("pom", "pom.xml", own),
    )
    pom = await client.get(f"{HELD}/1.0/app-1.0.pom", headers=root)
    sources = await client.get(f"{HELD}/1.0/app-1.0-sources.jar", headers=root)

    assert response.status_code == 201, response.text
    assert len(response.json()["files"]) == 3 and len(response.json()["components"]) == 1
    assert (pom.content, sources.content) == (own, b"sources")


async def test_no_pom_is_written_for_whoever_wants_none(client, releases, root):
    response = await send(client, root, {**APP, "generate_pom": "false"}, ("file", "app.jar", JAR))
    pom = await client.get(f"{HELD}/1.0/app-1.0.pom", headers=root)

    assert response.status_code == 201, response.text
    assert pom.status_code == 404


async def test_a_file_added_to_a_version_leaves_its_pom_alone(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    address = "/api/v1/content/once/upload"
    own = b"<project><modelVersion>4.0.0</modelVersion><name>Ours</name></project>"
    first = await send(
        client, root, APP, ("file", "app.jar", JAR), ("pom", "pom.xml", own), to=address
    )

    later = await send(client, root, APP, ("file.sources", "s.jar", b"sources"), to=address)
    pom = await client.get("/repository/once/com/acme/app/1.0/app-1.0.pom", headers=root)

    assert (first.status_code, later.status_code) == (201, 201), later.text
    assert [file["path"] for file in later.json()["files"]] == [
        "com/acme/app/1.0/app-1.0-sources.jar"
    ]
    assert pom.content == own


async def test_what_is_held_is_not_replaced_where_that_is_not_allowed(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    address = "/api/v1/content/once/upload"
    await send(client, root, APP, ("file", "app.jar", JAR), to=address)

    again = await send(
        client, root, APP, ("file.sources", "s.jar", b"new"), ("file", "app.jar", b"x"), to=address
    )
    jar = await client.get("/repository/once/com/acme/app/1.0/app-1.0.jar", headers=root)
    sources = await client.get(
        "/repository/once/com/acme/app/1.0/app-1.0-sources.jar", headers=root
    )

    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert (jar.content, sources.status_code) == (JAR, 404)  # all of the upload, or none


async def test_a_repository_takes_the_versions_its_policy_says(client, releases, snapshots, root):
    snapshot = {**APP, "version": "1.0-SNAPSHOT"}

    refused = await send(client, root, snapshot, ("file", "app.jar", JAR))
    wrong = await send(
        client, root, APP, ("file", "app.jar", JAR), to="/api/v1/content/snapshots/upload"
    )
    taken = await send(
        client, root, snapshot, ("file", "app.jar", JAR), to="/api/v1/content/snapshots/upload"
    )
    listed = await client.get(
        "/repository/snapshots/com/acme/app/1.0-SNAPSHOT/maven-metadata.xml", headers=root
    )
    jar = await client.get(
        "/repository/snapshots/com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT.jar", headers=root
    )

    for response in (refused, wrong):
        assert (response.status_code, error_code(response)) == (400, "version_policy_violation")
    assert taken.status_code == 201, taken.text
    assert "<version>1.0-SNAPSHOT</version>" in listed.text
    assert jar.content == JAR


async def test_a_form_that_does_not_say_what_to_store_is_refused(client, releases, root):
    no_version = await send(
        client, root, {"group": "com.acme", "artifact": "app"}, ("file", "a.jar", JAR)
    )
    no_kind = await send(client, root, APP, ("file", "README", b"text"))
    misspelt = await send(client, root, {**APP, "clasifier": "x"}, ("file", "a.jar", JAR))
    tree = await client.get("/api/v1/content/releases/tree", headers=root)

    for response, field in ((no_version, "version"), (no_kind, "file"), (misspelt, "clasifier")):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
        assert [detail["field"] for detail in response.json()["error"]["details"]] == [field]
    assert tree.json()["items"] == []


async def test_a_checksum_is_not_uploaded_as_a_file(client, releases, root):
    """A folder of a local repository, sent whole, has a `.sha1` beside every file."""
    response = await send(
        client, root, APP, ("file", "app-1.0.jar", JAR), ("file", "app-1.0.jar.sha1", b"0" * 40)
    )
    tree = await client.get("/api/v1/content/releases/tree", headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert "computed" in response.json()["error"]["details"][0]["message"]
    assert tree.json()["items"] == []
