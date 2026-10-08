import copy

from sqlalchemy import func, select

from megooarti.repositories import service
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.npm.conftest import URL, create, publish

DOCUMENT = f"{URL}/left-pad"
TAGS = f"{URL}/-/package/left-pad/dist-tags"


async def document(client, headers, url: str = DOCUMENT) -> dict:
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def three_versions(client, root) -> None:
    for version in ("1.0.0", "1.1.0", "2.0.0"):
        response = await publish(client, root, "left-pad", version)
        assert response.status_code == 201, response.text


async def account(db, make_user, name: str, *actions: str, repository: str = "npm") -> dict:
    """A user allowed exactly these actions on a repository. Returns their headers."""
    permissions = [f"repository:npm:{repository}:{action}" for action in actions]
    await roles.create_role(db, f"role-of-{name}", "", permissions, [])
    await db.commit()
    await make_user(name, roles=[f"role-of-{name}"])
    return basic(name, PASSWORD)


async def test_dist_tags_are_listed_set_and_removed(client, registry, root):
    await three_versions(client, root)

    listed = await client.get(TAGS, headers=root)
    added = await client.put(f"{TAGS}/stable", json="1.1.0", headers=root)
    moved = await client.put(f"{TAGS}/latest", json="1.1.0", headers=root)
    after_adding = (await client.get(TAGS, headers=root)).json()
    removed = await client.delete(f"{TAGS}/stable", headers=root)

    assert (listed.status_code, listed.json()) == (200, {"latest": "2.0.0"})
    assert (added.status_code, moved.status_code, removed.status_code) == (200, 200, 200)
    assert after_adding == {"latest": "1.1.0", "stable": "1.1.0"}
    assert (await document(client, root))["dist-tags"] == {"latest": "1.1.0"}


async def test_a_tag_must_name_a_version_that_exists(client, registry, root):
    await three_versions(client, root)

    missing_version = await client.put(f"{TAGS}/beta", json="9.9.9", headers=root)
    not_a_string = await client.put(f"{TAGS}/beta", json={"version": "1.0.0"}, headers=root)
    latest = await client.delete(f"{TAGS}/latest", headers=root)
    no_package = await client.get(f"{URL}/-/package/nothing/dist-tags", headers=root)
    wrong_method = await client.delete(TAGS, headers=root)

    assert (missing_version.status_code, error_code(missing_version)) == (404, "not_found")
    assert (not_a_string.status_code, error_code(not_a_string)) == (400, "invalid_package")
    assert (latest.status_code, error_code(latest)) == (400, "invalid_package")
    assert no_package.status_code == 404
    assert (wrong_method.status_code, error_code(wrong_method)) == (405, "method_not_allowed")
    assert (await client.get(TAGS, headers=root)).json() == {"latest": "2.0.0"}


async def test_the_tags_are_kept_in_a_document_nobody_downloads(client, registry, root, db):
    await three_versions(client, root)
    await client.put(f"{TAGS}/stable", json="1.1.0", headers=root)

    kept = await db.scalar(select(Asset).where(Asset.kind == "metadata"))

    assert (kept.path, kept.component_id) == ("-/package/left-pad/dist-tags", None)
    assert await db.scalar(select(func.count()).select_from(Asset)) == 4


async def test_deprecating_changes_the_stored_manifest(client, registry, root):
    await three_versions(client, root)
    sent = await document(client, root)
    sent["versions"]["1.0.0"]["deprecated"] = "use 2.0.0"
    sent["versions"]["1.1.0"]["description"] = "edits to anything else are ignored"

    deprecated = await client.put(f"{DOCUMENT}/-rev/{sent['_rev']}", json=sent, headers=root)
    after = await document(client, root)
    sent = copy.deepcopy(after)
    sent["versions"]["1.0.0"]["deprecated"] = ""  # how npm lifts a deprecation
    lifted = await client.put(DOCUMENT, json=sent, headers=root)

    assert (deprecated.status_code, lifted.status_code) == (200, 200)
    assert after["versions"]["1.0.0"]["deprecated"] == "use 2.0.0"
    assert "description" not in after["versions"]["1.1.0"]
    assert list(after["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]
    assert "deprecated" not in (await document(client, root))["versions"]["1.0.0"]


async def test_unpublishing_one_version_as_npm_does_it(client, registry, root):
    await three_versions(client, root)
    sent = await document(client, root)
    link = sent["versions"]["2.0.0"]["dist"]["tarball"].removeprefix("https://test")
    del sent["versions"]["2.0.0"]
    sent["dist-tags"] = {"latest": "1.1.0"}

    updated = await client.put(f"{DOCUMENT}/-rev/{sent['_rev']}", json=sent, headers=root)
    tarball = await client.delete(f"{link}/-rev/anything", headers=root)

    after = await document(client, root)
    assert (updated.status_code, tarball.status_code) == (200, 200)  # already gone is fine
    assert list(after["versions"]) == ["1.0.0", "1.1.0"]
    assert after["dist-tags"] == {"latest": "1.1.0"}
    assert (await client.get(link, headers=root)).status_code == 404


async def test_removing_the_latest_version_moves_latest_to_the_highest_left(client, registry, root):
    await three_versions(client, root)

    removed = await client.delete(f"{URL}/left-pad/-/left-pad-2.0.0.tgz", headers=root)

    assert removed.status_code == 200
    assert (await document(client, root))["dist-tags"] == {"latest": "1.1.0"}
    assert (await client.get(TAGS, headers=root)).json() == {"latest": "1.1.0"}


async def test_an_update_that_omits_versions_removes_nothing(client, registry, root):
    await three_versions(client, root)

    response = await client.put(DOCUMENT, json={"name": "left-pad"}, headers=root)

    assert response.status_code == 200
    assert list((await document(client, root))["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]


async def test_unpublishing_the_whole_package(client, registry, root, db):
    await three_versions(client, root)
    await client.put(f"{TAGS}/stable", json="1.0.0", headers=root)

    removed = await client.delete(f"{DOCUMENT}/-rev/anything", headers=root)
    again = await client.delete(DOCUMENT, headers=root)

    assert (removed.status_code, removed.json()) == (200, {"ok": True})
    assert (again.status_code, error_code(again)) == (404, "not_found")
    assert (await client.get(DOCUMENT, headers=root)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_an_update_to_a_package_that_is_not_there_is_not_found(client, registry, root):
    response = await client.put(DOCUMENT, json={"name": "left-pad", "versions": {}}, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_each_change_needs_its_own_permission(client, registry, root, make_user, db):
    await three_versions(client, root)
    publisher = await account(db, make_user, "pat", "read", "add")
    editor = await account(db, make_user, "eve", "read", "edit")
    remover = await account(db, make_user, "del", "read", "edit", "delete")
    reader = await account(db, make_user, "rae", "read")
    tarball = f"{URL}/left-pad/-/left-pad-1.1.0.tgz"

    async def deprecating(headers):
        sent = await document(client, root)
        sent["versions"]["1.0.0"]["deprecated"] = "old"
        return await client.put(DOCUMENT, json=sent, headers=headers)

    async def removing(headers):
        sent = await document(client, root)
        del sent["versions"]["2.0.0"]
        return await client.put(DOCUMENT, json=sent, headers=headers)

    outcomes = {
        "reader deprecates": await deprecating(reader),
        "publisher deprecates": await deprecating(publisher),
        "editor deprecates": await deprecating(editor),
        "editor removes a version": await removing(editor),
        "editor deletes a tarball": await client.delete(tarball, headers=editor),
        "editor deletes the package": await client.delete(DOCUMENT, headers=editor),
        "reader sets a tag": await client.put(f"{TAGS}/x", json="1.0.0", headers=reader),
        "publisher sets a tag": await client.put(f"{TAGS}/x", json="1.0.0", headers=publisher),
        "remover removes a version": await removing(remover),
        "remover deletes a tarball": await client.delete(tarball, headers=remover),
    }

    assert {name: response.status_code for name, response in outcomes.items()} == {
        "reader deprecates": 403,
        "publisher deprecates": 403,
        "editor deprecates": 200,
        "editor removes a version": 403,
        "editor deletes a tarball": 403,
        "editor deletes the package": 403,
        "reader sets a tag": 403,
        "publisher sets a tag": 200,
        "remover removes a version": 200,
        "remover deletes a tarball": 200,
    }
    after = await document(client, root)
    assert list(after["versions"]) == ["1.0.0"]
    assert after["versions"]["1.0.0"]["deprecated"] == "old"


async def test_a_read_only_repository_takes_no_changes(client, db, root):
    repository = await create(db, "open")
    await publish(client, root, "left-pad", "1.0.0", repository="open")
    await service.update_repository(
        db, repository, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
    )
    await db.commit()
    base = "/repository/open"

    attempts = [
        await client.put(
            f"{base}/left-pad", json={"name": "left-pad", "versions": {}}, headers=root
        ),
        await client.delete(f"{base}/left-pad", headers=root),
        await client.delete(f"{base}/left-pad/-/left-pad-1.0.0.tgz", headers=root),
        await client.put(f"{base}/-/package/left-pad/dist-tags/x", json="1.0.0", headers=root),
        await client.delete(f"{base}/-/package/left-pad/dist-tags/x", headers=root),
    ]

    assert [error_code(response) for response in attempts] == ["repository_read_only"] * 5
    assert (await client.get(f"{base}/left-pad", headers=root)).status_code == 200


async def test_an_update_from_a_stale_document_changes_nothing(client, registry, root):
    await publish(client, root, "left-pad", "1.0.0")
    read_earlier = await document(client, root)
    await publish(client, root, "left-pad", "1.1.0")  # by someone else, meanwhile
    read_earlier["versions"]["1.0.0"]["deprecated"] = "old"

    response = await client.put(DOCUMENT, json=read_earlier, headers=root)

    after = await document(client, root)
    assert (response.status_code, error_code(response)) == (409, "conflict")
    assert list(after["versions"]) == ["1.0.0", "1.1.0"]
    assert "deprecated" not in after["versions"]["1.0.0"]


async def test_an_update_cannot_name_a_version_that_is_not_stored(client, registry, root):
    await three_versions(client, root)
    sent = await document(client, root)
    sent["versions"]["3.0.0"] = {"name": "left-pad", "version": "3.0.0"}

    response = await client.put(DOCUMENT, json=sent, headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert list((await document(client, root))["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]


async def test_empty_attachments_are_not_an_update(client, registry, root):
    await three_versions(client, root)
    sent = {"name": "left-pad", "versions": {"1.0.0": {}}, "_attachments": {}}

    response = await client.put(DOCUMENT, json=sent, headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert list((await document(client, root))["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]


async def test_a_package_has_a_limited_number_of_dist_tags(client, registry, root):
    await three_versions(client, root)
    sent = await document(client, root)
    sent["dist-tags"] = {f"tag-{number}": "1.0.0" for number in range(251)}

    too_many = await client.put(DOCUMENT, json=sent, headers=root)
    still_works = await publish(client, root, "left-pad", "3.0.0")

    assert (too_many.status_code, error_code(too_many)) == (400, "invalid_package")
    assert still_works.status_code == 201
    assert (await client.get(TAGS, headers=root)).json() == {"latest": "3.0.0"}
