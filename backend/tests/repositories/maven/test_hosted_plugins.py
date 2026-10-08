from sqlalchemy import func, select

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.metadata import Metadata, Plugin
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

GROUP = "/repository/releases/com/acme/maven-metadata.xml"
ACME = Plugin("Acme Plugin", "acme", "acme-maven-plugin")


def group_metadata(*plugins: Plugin) -> bytes:
    return metadata.serialise(Metadata(plugins=plugins))


def jar_of(artifact: str, version: str = "1.0", repository: str = "releases") -> str:
    return f"/repository/{repository}/com/acme/{artifact}/{version}/{artifact}-{version}.jar"


async def deploy(client, root, artifact: str, version: str = "1.0") -> None:
    response = await client.put(jar_of(artifact, version), content=b"x", headers=root)
    assert response.status_code == 201, response.text


async def listed(client, root, url: str = GROUP) -> Metadata:
    response = await client.get(url, headers=root)
    assert response.status_code == 200, response.text
    return metadata.parse(response.content)


async def test_plugin_prefixes_are_kept_from_uploaded_group_metadata(client, releases, root):
    await deploy(client, root, "acme-maven-plugin")
    # Whatever else the client wrote is not kept: only the plugin entry is.
    client_made = Metadata(group_id="made.up", versions=("9.9",), latest="9.9", plugins=(ACME,))

    uploaded = await client.put(GROUP, content=metadata.serialise(client_made), headers=root)

    document = await listed(client, root)
    assert uploaded.status_code == 201
    assert document == Metadata(plugins=(ACME,))


async def test_a_second_plugin_is_merged_with_the_first(client, releases, root):
    other = Plugin("Other Plugin", "other", "other-maven-plugin")
    await deploy(client, root, "acme-maven-plugin")
    await deploy(client, root, "other-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    await client.put(GROUP, content=group_metadata(other), headers=root)

    assert (await listed(client, root)).plugins == (ACME, other)


async def test_a_newer_upload_wins_for_the_same_plugin(client, releases, root):
    renamed = Plugin("Acme Plugin 2", "acme2", "acme-maven-plugin")
    never_deployed = Plugin("Ghost", "ghost", "ghost-maven-plugin")
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    await client.put(GROUP, content=group_metadata(renamed, never_deployed), headers=root)

    assert (await listed(client, root)).plugins == (renamed,)


async def test_a_plugin_that_was_never_deployed_is_not_kept(client, releases, root, db):
    uploaded = await client.put(GROUP, content=group_metadata(ACME), headers=root)

    assert uploaded.status_code == 201
    assert (await client.get(GROUP, headers=root)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_a_plugin_disappears_with_its_last_file(client, releases, root):
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    await client.delete(jar_of("acme-maven-plugin"), headers=root)

    assert (await client.get(GROUP, headers=root)).status_code == 404


async def test_a_path_can_be_both_an_artifact_and_a_group(client, releases, root):
    # com/acme is the artifact "acme" of group "com", and also the group "com.acme".
    await client.put("/repository/releases/com/acme/1.0/acme-1.0.jar", content=b"x", headers=root)
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    document = await listed(client, root)

    assert (document.group_id, document.artifact_id) == ("com", "acme")
    assert document.versions == ("1.0",)
    assert document.plugins == (ACME,)


async def test_the_stored_record_is_never_served_as_a_file(client, releases, root, db):
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    record = await db.scalar(select(Asset).where(Asset.kind == "metadata"))
    removed = await client.delete(GROUP, headers=root)

    assert (record.path, record.component_id) == ("com/acme/maven-metadata.xml", None)
    assert (removed.status_code, error_code(removed)) == (405, "method_not_allowed")


async def test_plugins_at_a_path_that_cannot_be_a_group_are_dropped(client, releases, root, db):
    url = "/repository/releases/com/acme/my.app/maven-metadata.xml"

    uploaded = await client.put(url, content=group_metadata(ACME), headers=root)
    unreadable = await client.put(url, content=b"not xml", headers=root)

    assert uploaded.status_code == 201
    assert (unreadable.status_code, error_code(unreadable)) == (400, "invalid_metadata")
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_an_account_that_may_only_add_completes_two_plugin_deploys(client, db, make_user):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    await roles.create_role(
        db, "deployers", "", ["repository:maven:once:add", "repository:maven:once:read"], []
    )
    await db.commit()
    await make_user("ci", roles=["deployers"])
    ci = basic("ci", PASSWORD)
    group = "/repository/once/com/acme/maven-metadata.xml"
    artifact = "/repository/once/com/acme/acme-maven-plugin/maven-metadata.xml"
    renamed = Plugin("Acme Plugin 2", "acme", "acme-maven-plugin")

    async def upload(url: str, content: bytes | str) -> int:
        return (await client.put(url, content=content, headers=ci)).status_code

    statuses = []
    for version, plugin in (("1.0", ACME), ("1.1", renamed)):
        jar = jar_of("acme-maven-plugin", version, "once")
        statuses.append(await upload(jar, b"x"))
        sha1 = (await client.get(f"{jar}.sha1", headers=ci)).text
        statuses.append(await upload(f"{jar}.sha1", sha1))
        statuses.append(await upload(artifact, b"<metadata/>"))
        statuses.append(await upload(group, group_metadata(plugin)))
    first_jar = jar_of("acme-maven-plugin", "1.0", "once")
    replaced = await client.put(first_jar, content=b"y", headers=ci)

    assert statuses == [201] * 8
    assert (await listed(client, ci, group)).plugins == (renamed,)
    assert (await listed(client, ci, artifact)).versions == ("1.0", "1.1")
    assert (replaced.status_code, error_code(replaced)) == (403, "forbidden")
