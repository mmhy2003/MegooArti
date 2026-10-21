"""Content by selector permissions (spec 10): the content route reads, writes and deletes
the paths a selector allows and refuses their neighbours, through a group as directly;
and a component's attributes are changed only where its file may be."""

from dataclasses import replace

import pytest

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import someone
from tests.repositories.test_content_components import Packaged, store

FILES = "/repository/files"


@pytest.fixture
async def kim(db, files, make_user) -> dict[str, str]:
    """Someone who may read, add and delete under /allowed/ in `files` and its group, and
    nothing else; with a file there, and one beside it, put by an administrator."""
    db.add(ContentSelector(name="allowed", expression='path =^ "/allowed/"'))
    await service.create_repository(
        db,
        name="files-group",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    await roles.create_role(
        db,
        "allowed-files",
        "",
        ["selector:allowed:raw:files:*", "selector:allowed:raw:files-group:read"],
        [],
    )
    await db.commit()
    root = basic("root", PASSWORD)
    await make_user("root", roles=["admin"])
    await make_user("kim", roles=["allowed-files"])
    return basic("kim", PASSWORD), root


async def test_a_selector_reads_the_paths_it_matches_and_not_their_neighbours(client, kim):
    kim, root = kim
    await client.put(f"{FILES}/allowed/a.txt", content=b"a", headers=root)
    await client.put(f"{FILES}/denied/b.txt", content=b"b", headers=root)

    allowed = await client.get(f"{FILES}/allowed/a.txt", headers=kim)
    denied = await client.get(f"{FILES}/denied/b.txt", headers=kim)
    nobody = await client.get(f"{FILES}/allowed/a.txt")

    assert (allowed.status_code, allowed.content) == (200, b"a")
    assert (denied.status_code, error_code(denied)) == (403, "forbidden")
    assert nobody.status_code == 401


async def test_a_selector_writes_and_deletes_the_paths_it_matches_only(client, kim):
    kim, root = kim
    await client.put(f"{FILES}/denied/b.txt", content=b"b", headers=root)

    added = await client.put(f"{FILES}/allowed/new.txt", content=b"new", headers=kim)
    refused = await client.put(f"{FILES}/denied/new.txt", content=b"new", headers=kim)
    deleted = await client.delete(f"{FILES}/allowed/new.txt", headers=kim)
    kept = await client.delete(f"{FILES}/denied/b.txt", headers=kim)

    assert added.status_code == 201
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert deleted.status_code == 204
    assert (kept.status_code, error_code(kept)) == (403, "forbidden")
    assert (await client.get(f"{FILES}/denied/b.txt", headers=root)).content == b"b"


async def test_through_a_group_a_selector_reads_the_paths_it_matches_only(client, kim):
    kim, root = kim
    await client.put(f"{FILES}/allowed/a.txt", content=b"a", headers=root)
    await client.put(f"{FILES}/denied/b.txt", content=b"b", headers=root)

    allowed = await client.get("/repository/files-group/allowed/a.txt", headers=kim)
    denied = await client.get("/repository/files-group/denied/b.txt", headers=kim)

    assert (allowed.status_code, allowed.content) == (200, b"a")
    assert denied.status_code == 403


async def test_a_components_attributes_change_where_its_file_may_be_edited(db, files, context_for):
    owner = await context_for(files, someone("*"))
    owner.format = Packaged()
    await store(owner, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    await store(owner, "other/tool/1.0/tool.tgz", component_attributes={"n": 1})
    acme = someone("selector:acme:raw:files:edit")
    editor = replace(acme, selectors={"acme": 'path =^ "/acme/"'})
    context = await context_for(files, editor)

    changed = await context.annotate("acme", "app", "1.0", {"n": 2}, path="acme/app/1.0/app.tgz")
    with pytest.raises(ApiError) as refused:
        await context.annotate("other", "tool", "1.0", {"n": 2}, path="other/tool/1.0/tool.tgz")

    assert changed is True
    assert refused.value.status_code == 403


async def test_a_path_written_another_way_is_not_served_past_a_selector(client, db, kim, make_user):
    _, root = kim
    db.add(ContentSelector(name="open", expression='not path =^ "/secret/"'))
    await roles.create_role(db, "open-files", "", ["selector:open:raw:files:read"], [])
    await db.commit()
    await make_user("nia", roles=["open-files"])
    nia = basic("nia", PASSWORD)
    await client.put(f"{FILES}/secret/x.txt", content=b"secret", headers=root)

    straight = await client.get(f"{FILES}/secret/x.txt", headers=nia)
    dotted = await client.get(f"{FILES}/%2E/secret/x.txt", headers=nia)
    doubled = await client.get(f"{FILES}/%2Fsecret/x.txt", headers=nia)

    assert straight.status_code == 403
    for other in (dotted, doubled):
        assert other.status_code != 200, other.text
        assert other.content != b"secret"


async def test_a_selector_changed_reaches_what_it_says_at_once(client, kim, make_user):
    kim, root = kim
    await client.put(f"{FILES}/allowed/a.txt", content=b"a", headers=root)
    before = await client.get(f"{FILES}/allowed/a.txt", headers=kim)

    changed = await client.put(
        "/api/v1/content-selectors/allowed",
        json={"description": "", "expression": 'path =^ "/elsewhere/"'},
        headers=root,
    )
    after = await client.get(f"{FILES}/allowed/a.txt", headers=kim)

    assert (before.status_code, changed.status_code, after.status_code) == (200, 200, 403)
