import pytest
from sqlalchemy import func, select

from megooarti.errors import ApiError
from megooarti.security import roles, sessions, tokens, users
from megooarti.security.models import ApiToken, UserSession
from megooarti.security.passwords import verify_password
from tests.accounts import PASSWORD
from tests.security.conftest import NOW


async def create(db, username="Dana", **fields):
    fields.setdefault("display_name", "Dana Smith")
    fields.setdefault("email", None)
    fields.setdefault("password", PASSWORD)
    fields.setdefault("role_names", [])
    fields.setdefault("must_change_password", False)
    return await users.create_user(db, username=username, **fields)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def session_count(db, user) -> int:
    return await db.scalar(
        select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
    )


async def start_session(db, user):
    record, _ = await sessions.create_session(
        db, user.id, ip="10.0.0.1", user_agent="pytest", now=NOW, lifetime_seconds=3600
    )
    return record


async def test_create_stores_a_lower_case_username_and_a_password_hash(db):
    user = await create(db, "  Dana ", email="dana@example.org", role_names=["anonymous"])

    assert user.username == "dana"
    assert user.password_hash != PASSWORD
    assert verify_password(user.password_hash, PASSWORD)
    view = await users.describe(db, user)
    assert (view.username, view.email, view.status, view.roles) == (
        "dana",
        "dana@example.org",
        "active",
        ["anonymous"],
    )
    assert (view.builtin, view.must_change_password, view.last_login_at) == (False, False, None)


async def test_usernames_are_unique_whatever_the_case(db):
    await create(db, "dana")
    assert (await error_of(create(db, "DANA"))).code == "conflict"


async def test_lookup_by_username_ignores_case_and_spaces(db):
    user = await create(db, "dana")
    assert (await users.get_user_by_username(db, " DaNa ")).id == user.id
    assert await users.get_user_by_username(db, "nobody") is None


@pytest.mark.parametrize("password", ["short", "dana"])
async def test_an_unacceptable_password_is_a_validation_error(db, password):
    error = await error_of(create(db, "dana", password=password))
    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == "password"


async def test_an_unknown_role_is_a_validation_error(db):
    assert (await error_of(create(db, role_names=["ghost"]))).code == "validation_error"


async def test_patterns_come_from_the_users_roles(db):
    await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    await roles.create_role(db, "team", "", ["admin:users:read"], ["readers"])
    user = await create(db, role_names=["team"])

    assert await users.user_patterns(db, user) == {"admin:users:read", "repository:*:*:read"}


async def test_update_changes_only_the_given_fields(db):
    user = await create(db, email="dana@example.org", role_names=["anonymous"])

    await users.update_user(db, user, {"display_name": "D. Smith", "email": None})

    view = await users.describe(db, user)
    assert (view.display_name, view.email, view.roles) == ("D. Smith", None, ["anonymous"])


async def test_update_can_replace_roles(db):
    await roles.create_role(db, "readers", "", [], [])
    user = await create(db, role_names=["anonymous"])

    await users.update_user(db, user, {"roles": ["readers"]})

    assert (await users.describe(db, user)).roles == ["readers"]


async def test_disabling_a_user_ends_their_sessions(db):
    user = await create(db)
    await start_session(db, user)

    await users.update_user(db, user, {"status": "disabled"})

    assert user.status == "disabled"
    assert await session_count(db, user) == 0


async def test_set_password_replaces_the_hash_and_ends_other_sessions(db):
    user = await create(db, must_change_password=True)
    keep = await start_session(db, user)
    await start_session(db, user)

    await users.set_password(
        db, user, "another good password", must_change_password=False, keep_session_id=keep.id
    )

    assert verify_password(user.password_hash, "another good password")
    assert user.must_change_password is False
    assert await db.scalar(select(UserSession.id).where(UserSession.user_id == user.id)) == keep.id


async def test_set_password_applies_the_password_rules(db):
    user = await create(db)
    error = await error_of(users.set_password(db, user, "short", must_change_password=False))
    assert error.code == "validation_error"


async def test_the_anonymous_user_cannot_have_a_password(db):
    anonymous = await users.get_user_by_username(db, "anonymous")
    error = await error_of(users.set_password(db, anonymous, PASSWORD, must_change_password=False))
    assert error.code == "builtin_protected"


async def test_built_in_users_cannot_be_deleted(db):
    admin = await users.get_user_by_username(db, "admin")
    assert (await error_of(users.delete_user(db, admin))).code == "builtin_protected"


async def test_deleting_a_user_removes_their_sessions_and_tokens(db):
    user = await create(db)
    await start_session(db, user)
    await tokens.create_token(db, user.id, name="ci", expires_at=None, scopes=None)

    await users.delete_user(db, user)

    assert await users.get_user_by_username(db, "dana") is None
    assert await db.scalar(select(func.count()).select_from(UserSession)) == 0
    assert await db.scalar(select(func.count()).select_from(ApiToken)) == 0


async def test_list_is_paged_in_username_order(db):
    for name in ("zoe", "bob"):
        await create(db, name)

    first, total = await users.list_users(db, limit=3, offset=0)

    assert total == 4
    assert [view.username for view in first] == ["admin", "anonymous", "bob"]


async def test_make_user_fixture_creates_someone_who_can_sign_in(make_user, db):
    created = await make_user("dana", roles=["admin"])

    user = await users.get_user(db, created.id)

    assert verify_password(user.password_hash, PASSWORD)
    assert (await users.describe(db, user)).roles == ["admin"]


@pytest.mark.parametrize("username", ["mga_dana", "MGA_", " mga_" + "x" * 43])
async def test_a_user_name_cannot_look_like_a_token(db, username):
    error = await error_of(create(db, username))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == "username"


@pytest.mark.parametrize("username", ["__token__", " __TOKEN__ "])
async def test_the_name_that_stands_for_a_token_cannot_be_a_users(db, username):
    error = await error_of(create(db, username))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == "username"
    assert await users.get_user_by_username(db, "__token__") is None
