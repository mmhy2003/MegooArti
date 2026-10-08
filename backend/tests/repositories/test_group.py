import pytest
from sqlalchemy import insert
from starlette.requests import Request

from megooarti.repositories import group, service
from megooarti.repositories.models import RepositoryMember
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import someone

FILE = "docs/a.txt"
GROUP = f"/repository/all/{FILE}"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, type: str = "hosted", **settings):
    repository = await service.create_repository(
        db, name=name, format="raw", type=type, online=True, blob_store=None, **settings
    )
    await db.commit()
    return repository


@pytest.fixture
async def everything(db):
    """Hosted `one` and `two`, presented in that order by the group `all`."""
    await create(db, "one")
    await create(db, "two")
    return await create(db, "all", "group", group={"members": ["one", "two"]})


async def put(client, root, repository: str, content: bytes, path: str = FILE) -> None:
    response = await client.put(f"/repository/{repository}/{path}", content=content, headers=root)
    assert response.status_code in (201, 204)


async def reorder(db, group, members: list[str]) -> None:
    await service.update_repository(db, group, online=True, group={"members": members})
    await db.commit()


async def test_the_first_member_that_has_the_path_answers(client, root, everything, db):
    await put(client, root, "one", b"from one")
    await put(client, root, "two", b"from two")

    first = await client.get(GROUP, headers=root)
    await reorder(db, everything, ["two", "one"])
    second = await client.get(GROUP, headers=root)

    assert (first.status_code, first.content) == (200, b"from one")
    assert second.content == b"from two"
    assert first.headers["Content-Disposition"].startswith('attachment; filename="a.txt"')


async def test_a_later_member_answers_when_earlier_ones_lack_the_path(client, root, everything):
    await put(client, root, "two", b"only in two")

    assert (await client.get(GROUP, headers=root)).content == b"only in two"


async def test_not_found_when_no_member_has_the_path(client, root, everything):
    response = await client.get(GROUP, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_an_empty_group_has_nothing(client, root, db):
    await create(db, "all", "group")

    assert (await client.get(GROUP, headers=root)).status_code == 404


async def test_an_offline_member_is_skipped(client, root, everything, db):
    await put(client, root, "one", b"from one")
    await put(client, root, "two", b"from two")
    one = await service.get_repository(db, "one")
    await service.update_repository(db, one, online=False)
    await db.commit()

    assert (await client.get(GROUP, headers=root)).content == b"from two"


async def test_head_and_ranges_work_through_a_group(client, root, everything):
    await put(client, root, "one", b"hello, world")

    head = await client.head(GROUP, headers=root)
    partial = await client.get(GROUP, headers={**root, "Range": "bytes=7-"})

    assert (head.status_code, head.headers["Content-Length"]) == (200, "12")
    assert (partial.status_code, partial.content) == (206, b"world")


async def test_a_range_outside_the_file_is_reported_not_skipped(client, root, everything):
    await put(client, root, "one", b"short")
    await put(client, root, "two", b"a much longer file in the second member")

    response = await client.get(GROUP, headers={**root, "Range": "bytes=20-"})

    assert (response.status_code, error_code(response)) == (416, "range_not_satisfiable")


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
async def test_a_group_cannot_be_written_to(client, root, everything, method):
    response = await client.request(method, GROUP, content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"


async def test_a_proxy_member_fetches_and_caches_through_the_group(
    client, root, mirror, fake_remote, db
):
    fake_remote.files[f"files/{FILE}"] = b"from the remote"
    await create(db, "one")
    await create(db, "all", "group", group={"members": ["one", "mirror"]})

    first = await client.get(GROUP, headers=root)
    second = await client.get(GROUP, headers=root)

    assert (first.content, second.content) == (b"from the remote", b"from the remote")
    assert fake_remote.paths() == [f"/files/{FILE}"]


async def test_a_proxy_member_that_cannot_answer_is_passed_over(
    client, root, mirror, fake_remote, db
):
    fake_remote.down = True
    await create(db, "two")
    await create(db, "all", "group", group={"members": ["mirror", "two"]})
    await put(client, root, "two", b"from two")

    found = await client.get(GROUP, headers=root)
    absent = await client.get("/repository/all/elsewhere.bin", headers=root)

    assert found.content == b"from two"
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_a_group_inside_a_group(client, root, everything, db):
    await create(db, "three")
    await create(db, "outer", "group", group={"members": ["three", "all"]})
    await put(client, root, "two", b"deep inside")

    response = await client.get(f"/repository/outer/{FILE}", headers=root)

    assert response.content == b"deep inside"


async def test_permission_on_the_group_is_what_counts(client, root, everything, make_user, db):
    await roles.create_role(db, "group-readers", "", ["repository:raw:all:read"], [])
    await roles.create_role(db, "member-readers", "", ["repository:raw:one:read"], [])
    await db.commit()
    await make_user("gia", roles=["group-readers"])
    await make_user("max", roles=["member-readers"])
    await put(client, root, "one", b"from one")
    gia, max_ = basic("gia", PASSWORD), basic("max", PASSWORD)

    through_group = await client.get(GROUP, headers=gia)
    member_directly = await client.get(f"/repository/one/{FILE}", headers=gia)
    without_group_permission = await client.get(GROUP, headers=max_)

    assert through_group.content == b"from one"
    assert (member_directly.status_code, error_code(member_directly)) == (403, "forbidden")
    assert (without_group_permission.status_code, error_code(without_group_permission)) == (
        403,
        "forbidden",
    )


async def test_an_offline_group_is_unavailable(client, root, everything, db):
    await service.update_repository(db, everything, online=False, group={"members": ["one", "two"]})
    await db.commit()

    response = await client.get(GROUP, headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")


async def test_a_cycle_that_slipped_into_the_data_ends_in_not_found(client, root, db):
    first = await create(db, "all", "group")
    second = await create(db, "loop", "group", group={"members": ["all"]})
    await db.execute(
        insert(RepositoryMember).values(group_id=first.id, member_id=second.id, position=0)
    )
    await db.commit()

    response = await client.get(GROUP, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


def bare_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def test_member_contexts_are_the_online_members_in_order(db, everything, context_for):
    reader = someone("repository:raw:all:read")
    context = await context_for(everything, reader, outbound=bare_request)

    members = await group.member_contexts(context, bare_request())

    assert [member.repository.name for member in members] == ["one", "two"]
    assert all(member.principal is reader for member in members)
    assert all(member.outbound is bare_request for member in members)


async def test_an_offline_member_has_no_context(db, everything, context_for):
    one = await service.get_repository(db, "one")
    await service.update_repository(db, one, online=False)
    await db.commit()
    context = await context_for(everything, None)

    members = await group.member_contexts(context, bare_request())

    assert [member.repository.name for member in members] == ["two"]


async def test_a_group_gives_its_members_once_in_a_request(everything, context_for):
    context = await context_for(everything, None)
    request = bare_request()

    first = await group.member_contexts(context, request)
    again = await group.member_contexts(context, request)

    assert (len(first), again) == (2, [])


async def nested(db):
    """`outer` presents `three`, then the group `all` (`one`, `two`), then `one` again."""
    await create(db, "three")
    return await create(db, "outer", "group", group={"members": ["three", "all", "one"]})


def named(found: list[group.Leaf]) -> list[tuple[str, bool]]:
    return [(leaf.context.repository.name, leaf.online) for leaf in found]


async def test_leaves_are_every_repository_behind_a_group_in_order(db, everything, context_for):
    reader = someone("repository:raw:outer:read")
    context = await context_for(await nested(db), reader, outbound=bare_request)

    found = await group.leaves(context)
    again = await group.leaves(context)

    assert named(found) == [("three", True), ("one", True), ("two", True)]
    assert named(again) == named(found)  # unlike member_contexts, as often as it is asked
    assert all(leaf.context.principal is reader for leaf in found)
    assert all(leaf.context.outbound is bare_request for leaf in found)


async def test_leaves_include_what_is_offline_and_say_so(db, everything, context_for):
    context = await context_for(await nested(db), None)
    two = await service.get_repository(db, "two")
    await service.update_repository(db, two, online=False)
    await db.commit()

    one_offline = await group.leaves(context)
    await service.update_repository(db, everything, online=False, group={"members": ["one", "two"]})
    await db.commit()
    group_offline = await group.leaves(context)

    assert named(one_offline) == [("three", True), ("one", True), ("two", False)]
    # `one` is still a member of `outer` in its own right, and is tried where that puts it.
    assert named(group_offline) == [("three", True), ("two", False), ("one", True)]


async def test_leaves_of_a_cycle_that_slipped_into_the_data_end(db, context_for):
    first = await create(db, "all", "group")
    second = await create(db, "loop", "group", group={"members": ["all"]})
    await db.execute(
        insert(RepositoryMember).values(group_id=first.id, member_id=second.id, position=0)
    )
    await db.commit()

    assert await group.leaves(await context_for(first, None)) == []
