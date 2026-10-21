"""What a selector permission lets a caller see (spec 10): the repositories it names, and
in them only the folders, files and components it reaches, in the content API, search
and MCP; and a folder deleted is deleted where it may be."""

import uuid

import pytest

from megooarti.repositories import service
from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic
from tests.repositories.conftest import someone
from tests.repositories.test_content_components import Packaged, store

CONTENT = "/api/v1/content"
ALLOWED = ["acme/app/1.0/app.tgz", "acme/app/1.0/app.pom", "acme/lib/2.0/lib.tgz"]
DENIED = ["other/tool/1.0/tool.tgz", "acme-private/x/1.0/x.tgz"]


@pytest.fixture
async def kim(db, files, context_for, make_user) -> dict[str, str]:
    """Someone whose selectors reach /acme/ in `files` (browse and delete) and whose other
    one names `npm-only`, a repository of another format: with files there and beside."""
    owner = await context_for(files, someone("*"))
    owner.format = Packaged()
    for path in ALLOWED + DENIED:
        await store(owner, path)
    await db.commit()
    await service.create_repository(
        db,
        name="secret",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=None,
        format_config={},
    )
    db.add_all(
        [
            ContentSelector(name="acme", expression='path =^ "/acme/"'),
            ContentSelector(name="pattern", expression='path =~ "/acme/.*\\\\.tgz"'),
            ContentSelector(name="npm-only", expression='format == "npm"'),
        ]
    )
    await roles.create_role(
        db,
        "acme",
        "",
        [
            "selector:acme:raw:files:browse",
            "selector:acme:raw:files:delete",
            "selector:npm-only:raw:secret:browse",
        ],
        [],
    )
    await roles.create_role(db, "tgz", "", ["selector:pattern:raw:files:browse"], [])
    await db.commit()
    await make_user("kim", roles=["acme"])
    await make_user("tia", roles=["tgz"])
    return basic("kim", PASSWORD)


async def test_only_the_repositories_a_selector_reaches_are_listed(client, kim):
    listed = await client.get(CONTENT, headers=kim)
    secret = await client.get(f"{CONTENT}/secret", headers=kim)

    assert [found["name"] for found in listed.json()["items"]] == ["files"]
    assert secret.status_code == 403  # named, but by a selector of another format


async def test_a_folder_shows_what_is_reached_and_one_that_holds_nothing_is_not_there(client, kim):
    root = await client.get(f"{CONTENT}/files/tree", headers=kim)
    acme = await client.get(f"{CONTENT}/files/tree", params={"path": "acme/app/1.0"}, headers=kim)
    other = await client.get(f"{CONTENT}/files/tree", params={"path": "other"}, headers=kim)

    assert [entry["name"] for entry in root.json()["items"]] == ["acme"]
    assert [entry["name"] for entry in acme.json()["items"]] == ["app.pom", "app.tgz"]
    assert other.status_code == 404


async def test_a_file_reached_is_shown_and_one_beside_it_is_not_there(client, kim):
    shown = await client.get(
        f"{CONTENT}/files/asset", params={"path": "acme/app/1.0/app.tgz"}, headers=kim
    )
    hidden = await client.get(
        f"{CONTENT}/files/asset", params={"path": "other/tool/1.0/tool.tgz"}, headers=kim
    )

    assert shown.status_code == 200
    assert hidden.status_code == 404


async def test_components_are_those_with_a_file_reached(client, kim):
    listed = await client.get(f"{CONTENT}/files/components", headers=kim)

    assert [found["name"] for found in listed.json()["items"]] == ["app", "lib"]
    assert listed.json()["total"] == 2


async def test_through_a_pattern_components_are_those_a_file_of_matches(client, kim):
    tia = basic("tia", PASSWORD)

    listed = await client.get(f"{CONTENT}/files/components", headers=tia)
    app = next(found for found in listed.json()["items"] if found["name"] == "app")
    detail = await client.get(f"{CONTENT}/files/components/{app['id']}", headers=tia)

    assert [found["name"] for found in listed.json()["items"]] == ["app", "lib"]
    assert [entry["path"] for entry in detail.json()["files"]] == ["acme/app/1.0/app.tgz"]


async def test_a_component_with_no_file_reached_is_not_there(client, kim, make_user):
    await make_user("root", roles=["admin"])
    every = await client.get(f"{CONTENT}/files/components", headers=basic("root", PASSWORD))
    tool = next(found["id"] for found in every.json()["items"] if found["name"] == "tool")

    hidden = await client.get(f"{CONTENT}/files/components/{tool}", headers=kim)

    assert hidden.status_code == 404


async def test_search_finds_only_components_with_a_file_reached(client, kim):
    found = await client.get("/api/v1/search", headers=kim)
    by_pattern = await client.get("/api/v1/search", params={"q": "tool"}, headers=kim)

    assert sorted(item["name"] for item in found.json()["items"]) == ["app", "lib"]
    assert found.json()["total"] == 2
    assert by_pattern.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_a_folder_deleted_loses_what_may_be_deleted_and_keeps_the_rest(
    client, kim, make_user
):
    deleted = await client.request(
        "DELETE", f"{CONTENT}/files/tree", params={"path": "acme"}, headers=kim
    )
    everything = await client.request(
        "DELETE", f"{CONTENT}/files/tree", params={"path": "other"}, headers=kim
    )
    await make_user("root", roles=["admin"])
    kept = await client.get(
        f"{CONTENT}/files/asset",
        params={"path": "other/tool/1.0/tool.tgz"},
        headers=basic("root", PASSWORD),
    )

    assert deleted.json()["deleted"] == 3
    assert everything.json()["deleted"] == 0
    assert kept.status_code == 200


async def test_a_folder_shows_what_is_reached_however_far_past_the_first_page(
    client, db, files, context_for, make_user
):
    owner = await context_for(files, someone("*"))
    for index in range(60):
        await store(owner, f"a{index:02}/f.txt")
    await store(owner, "zz/f.txt")
    await db.commit()
    db.add(ContentSelector(name="zz", expression='path =^ "/zz/"'))
    await roles.create_role(db, "zz", "", ["selector:zz:raw:files:browse"], [])
    await db.commit()
    await make_user("zed", roles=["zz"])

    root = await client.get(f"{CONTENT}/files/tree", headers=basic("zed", PASSWORD))

    assert [entry["name"] for entry in root.json()["items"]] == ["zz"]


async def test_very_many_components_left_out_through_a_pattern_are_listed_without_a_failure(
    client, kim, monkeypatch
):
    from megooarti.repositories import browse, reached, search

    async def many(db, by_id, conditions):
        kept = await reached.unreached(db, by_id, conditions)
        return [*kept, *(uuid.uuid4() for _ in range(40000))]

    # Where they are used: more ids left out than a statement may have parameters.
    monkeypatch.setattr(browse, "unreached", many)
    monkeypatch.setattr(search, "unreached", many)
    tia = basic("tia", PASSWORD)

    listed = await client.get(f"{CONTENT}/files/components", headers=tia)
    searched = await client.get("/api/v1/search", headers=tia)

    assert (listed.status_code, searched.status_code) == (200, 200)
    assert [found["name"] for found in listed.json()["items"]] == ["app", "lib"]
