import pytest

from megooarti.errors import ApiError
from megooarti.security import roles


async def code_of(awaitable) -> str:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value.code


async def test_create_and_describe(db):
    role = await roles.create_role(
        db, "developers", "People who publish", ["repository:*:*:read", "admin:users:read"], []
    )

    view = await roles.describe(db, role)

    assert view == roles.RoleView(
        name="developers",
        description="People who publish",
        builtin=False,
        permissions=["admin:users:read", "repository:*:*:read"],
        roles=[],
    )


async def test_a_duplicate_name_is_a_conflict(db):
    await roles.create_role(db, "developers", "", [], [])
    assert await code_of(roles.create_role(db, "developers", "", [], [])) == "conflict"


async def test_an_unknown_member_role_is_a_validation_error(db):
    assert await code_of(roles.create_role(db, "team", "", [], ["ghost"])) == "validation_error"


async def test_effective_patterns_follow_contained_roles(db):
    readers = await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    writers = await roles.create_role(db, "writers", "", ["repository:*:*:add"], ["readers"])
    leads = await roles.create_role(db, "leads", "", ["admin:users:read"], ["writers"])

    assert await roles.effective_patterns(db, [readers.id]) == {"repository:*:*:read"}
    assert await roles.effective_patterns(db, [leads.id]) == {
        "admin:users:read",
        "repository:*:*:add",
        "repository:*:*:read",
    }
    assert await roles.effective_patterns(db, []) == frozenset()
    assert (await roles.describe(db, writers)).roles == ["readers"]


async def test_a_role_cannot_contain_itself(db):
    role = await roles.create_role(db, "loop", "", [], [])
    assert await code_of(roles.update_role(db, role, "", [], ["loop"])) == "role_cycle"


async def test_an_indirect_cycle_is_rejected(db):
    inner = await roles.create_role(db, "inner", "", [], [])
    await roles.create_role(db, "middle", "", [], ["inner"])
    await roles.create_role(db, "outer", "", [], ["middle"])

    assert await code_of(roles.update_role(db, inner, "", [], ["outer"])) == "role_cycle"


async def test_update_replaces_description_patterns_and_members(db):
    await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    await roles.create_role(db, "auditors", "", ["admin:users:read"], [])
    role = await roles.create_role(db, "team", "old", ["admin:roles:read", "a:b"], ["readers"])

    await roles.update_role(db, role, "new", ["a:b", "c:d"], ["auditors"])

    view = await roles.describe(db, role)
    assert (view.description, view.permissions, view.roles) == ("new", ["a:b", "c:d"], ["auditors"])


async def test_the_admin_role_cannot_be_changed(db):
    admin = await roles.get_role(db, "admin")
    assert await code_of(roles.update_role(db, admin, "", [], [])) == "builtin_protected"


async def test_the_anonymous_role_can_be_changed_but_not_deleted(db):
    anonymous = await roles.get_role(db, "anonymous")

    await roles.update_role(db, anonymous, "Nothing", [], [])

    assert (await roles.describe(db, anonymous)).permissions == []
    assert await code_of(roles.delete_role(db, anonymous)) == "builtin_protected"


async def test_deleting_a_role_removes_it_from_roles_that_contained_it(db):
    readers = await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    team = await roles.create_role(db, "team", "", [], ["readers"])

    await roles.delete_role(db, readers)

    assert await roles.get_role(db, "readers") is None
    assert (await roles.describe(db, team)).roles == []


async def test_list_is_paged_in_name_order(db):
    for name in ("zeta", "beta"):
        await roles.create_role(db, name, "", [], [])

    first, total = await roles.list_roles(db, limit=3, offset=0)
    rest, _ = await roles.list_roles(db, limit=3, offset=3)

    assert total == 4
    assert [view.name for view in first] == ["admin", "anonymous", "beta"]
    assert [view.name for view in rest] == ["zeta"]
