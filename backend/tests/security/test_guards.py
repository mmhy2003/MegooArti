import pytest
from sqlalchemy import insert

from megooarti.errors import ApiError
from megooarti.security import roles
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import User, UserRole


async def add_user(db, username: str, role_name: str, **fields) -> User:
    user = User(username=username, display_name=username, password_hash="hash", **fields)
    db.add(user)
    await db.flush()
    role = await roles.get_role(db, role_name)
    await db.execute(insert(UserRole).values(user_id=user.id, role_id=role.id))
    return user


async def refused(db) -> bool:
    try:
        await ensure_administrator_remains(db)
    except ApiError as error:
        assert error.code == "last_administrator"
        assert error.status_code == 409
        return True
    return False


async def test_refused_when_no_administrator_has_a_password(db):
    # Straight after migration the built-in admin has no password yet.
    assert await refused(db)


async def test_passes_with_an_active_administrator_who_has_a_password(db):
    await add_user(db, "root", "admin")
    assert not await refused(db)


async def test_a_disabled_administrator_does_not_count(db):
    await add_user(db, "root", "admin", status="disabled")
    assert await refused(db)


async def test_full_access_through_a_contained_role_counts(db):
    await roles.create_role(db, "operators", "", [], ["admin"])
    await add_user(db, "olga", "operators")
    assert not await refused(db)


@pytest.mark.parametrize("patterns", [["admin"], ["admin:*"], ["*:*"]])
async def test_only_the_single_wildcard_counts_as_full_access(db, patterns):
    await roles.create_role(db, "nearly", "", patterns, [])
    await add_user(db, "nora", "nearly")
    assert await refused(db)
