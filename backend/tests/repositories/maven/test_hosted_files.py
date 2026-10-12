import pytest
from sqlalchemy import func, select

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

JAR = "/repository/releases/com/acme/app/1.0/app-1.0.jar"
POM = "/repository/releases/com/acme/app/1.0/app-1.0.pom"
BYTES = b"PK\x03\x04 pretend this is a jar"
SNAPSHOTS = "/repository/snapshots/com/acme/app/1.0-SNAPSHOT"


async def test_an_artifact_is_stored_served_and_given_its_component(client, releases, root, db):
    stored = await client.put(JAR, content=BYTES, headers=root)
    fetched = await client.get(JAR, headers=root)

    assert stored.status_code == 201
    assert (fetched.status_code, fetched.content) == (200, BYTES)
    assert fetched.headers["Content-Type"] == "application/java-archive"
    assert fetched.headers["Content-Disposition"].startswith('attachment; filename="app-1.0.jar"')
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("com.acme", "app", "1.0")


async def test_the_files_of_a_version_share_one_component(client, releases, root, db):
    await client.put(JAR, content=BYTES, headers=root)
    await client.put(POM, content=b"<project/>", headers={**root, "Content-Type": "text/weird"})

    assert await db.scalar(select(func.count()).select_from(Component)) == 1
    assert (await client.get(POM, headers=root)).headers["Content-Type"] == "application/xml"


@pytest.mark.parametrize(
    "path",
    ["notes/readme.txt", "com/acme/app/1.0/other-1.0.jar", "com.acme/app/1.0/app-1.0.jar"],
)
async def test_a_strict_repository_refuses_paths_outside_the_layout(client, releases, root, path):
    refused = await client.put(f"/repository/releases/{path}", content=b"x", headers=root)
    missing = await client.get(f"/repository/releases/{path}", headers=root)

    assert (refused.status_code, error_code(refused)) == (400, "invalid_path")
    assert (missing.status_code, error_code(missing)) == (404, "not_found")


async def test_a_permissive_repository_stores_other_paths_as_plain_files(client, db, root):
    await create(db, "loose", layout_policy="permissive")
    url = "/repository/loose/notes/readme.txt"

    stored = await client.put(url, content=b"hello", headers=root)

    assert stored.status_code == 201
    assert (await client.get(url, headers=root)).content == b"hello"
    assert await db.scalar(select(Asset.component_id)) is None


async def test_files_stored_while_permissive_stay_reachable_once_strict(client, db, root):
    loose = await create(db, "loose", layout_policy="permissive")
    url = "/repository/loose/notes/readme.txt"
    await client.put(url, content=b"hello", headers=root)
    await service.update_repository(
        db, loose, online=True, hosted=None, format_config={"layout_policy": "strict"}
    )
    await db.commit()

    another = await client.put("/repository/loose/notes/other.txt", content=b"x", headers=root)

    assert (another.status_code, error_code(another)) == (400, "invalid_path")
    assert (await client.get(url, headers=root)).content == b"hello"
    assert (await client.delete(url, headers=root)).status_code == 204


async def test_the_catalog_is_a_plain_file(client, releases, root, db):
    url = "/repository/releases/archetype-catalog.xml"

    stored = await client.put(url, content=b"<archetype-catalog/>", headers=root)

    assert stored.status_code == 201
    assert (await client.get(url, headers=root)).content == b"<archetype-catalog/>"
    assert await db.scalar(select(Asset.component_id)) is None


async def test_a_release_repository_refuses_snapshots(client, releases, root):
    url = "/repository/releases/com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-1.jar"

    refused = await client.put(url, content=BYTES, headers=root)

    assert (refused.status_code, error_code(refused)) == (400, "version_policy_violation")
    assert (await client.get(url, headers=root)).status_code == 404


async def test_a_snapshot_repository_refuses_releases(client, snapshots, root, db):
    release = await client.put(
        "/repository/snapshots/com/acme/app/1.0/app-1.0.jar", content=BYTES, headers=root
    )
    timestamped = await client.put(
        f"{SNAPSHOTS}/app-1.0-20261008.101500-1.jar", content=BYTES, headers=root
    )
    old_style = await client.put(f"{SNAPSHOTS}/app-1.0-SNAPSHOT.jar", content=BYTES, headers=root)

    assert (release.status_code, error_code(release)) == (400, "version_policy_violation")
    assert (timestamped.status_code, old_style.status_code) == (201, 201)
    component = await db.scalar(select(Component))
    assert (component.name, component.version) == ("app", "1.0-SNAPSHOT")


async def test_a_mixed_repository_accepts_both(client, db, root):
    await create(db, "mixed", version_policy="mixed")
    base = "/repository/mixed/com/acme/app"

    release = await client.put(f"{base}/1.0/app-1.0.jar", content=BYTES, headers=root)
    snapshot = await client.put(
        f"{base}/1.1-SNAPSHOT/app-1.1-SNAPSHOT.jar", content=BYTES, headers=root
    )

    assert (release.status_code, snapshot.status_code) == (201, 201)


async def test_the_deployment_policy_applies_to_artifacts(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    url = "/repository/once/com/acme/app/1.0/app-1.0.jar"
    await client.put(url, content=BYTES, headers=root)

    again = await client.put(url, content=b"different", headers=root)

    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert (await client.get(url, headers=root)).content == BYTES


async def test_an_artifact_can_be_deleted(client, releases, root, db):
    await client.put(JAR, content=BYTES, headers=root)

    assert (await client.delete(JAR, headers=root)).status_code == 204
    assert (await client.get(JAR, headers=root)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Component)) == 0


async def test_permissions_use_the_maven_format_name(client, releases, make_user, db):
    await roles.create_role(db, "deployers", "", ["repository:maven:releases:add"], [])
    await db.commit()
    await make_user("ci", roles=["deployers"])
    ci = basic("ci", PASSWORD)

    stored = await client.put(JAR, content=BYTES, headers=ci)
    read = await client.get(JAR, headers=ci)

    assert stored.status_code == 201
    assert (read.status_code, error_code(read)) == (403, "forbidden")


async def test_an_invalid_path_is_still_a_bad_request(client, releases, root):
    response = await client.get("/repository/releases/com//app", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_path")


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_other_methods_are_not_allowed(client, releases, root, method):
    response = await client.request(method, JAR, content=BYTES, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")


async def test_a_release_is_deployed_once_to_a_repository_that_was_given_no_policy(
    client, releases, snapshots, root
):
    # `releases` and `snapshots` are made with nothing said of redeploying (H1).
    await client.put(JAR, content=BYTES, headers=root)
    snapshot = f"{SNAPSHOTS}/app-1.0-SNAPSHOT.jar"
    await client.put(snapshot, content=BYTES, headers=root)

    again = await client.put(JAR, content=b"another build", headers=root)
    snapshot_again = await client.put(snapshot, content=b"another build", headers=root)

    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert (await client.get(JAR, headers=root)).content == BYTES
    assert snapshot_again.status_code in (200, 201, 204)
    assert (await client.get(snapshot, headers=root)).content == b"another build"
