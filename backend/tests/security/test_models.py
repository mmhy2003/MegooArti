from sqlalchemy import select

from megooarti.security.models import Role, RolePermission, User, UserRole


async def test_built_in_roles_exist_with_their_patterns(db):
    rows = await db.execute(
        select(Role.name, RolePermission.pattern)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(Role.builtin.is_(True))
        .order_by(Role.name, RolePermission.pattern)
    )
    assert [tuple(row) for row in rows] == [
        ("admin", "*"),
        ("anonymous", "repository:*:*:browse"),
        ("anonymous", "repository:*:*:read"),
    ]


async def test_built_in_users_exist_without_passwords(db):
    rows = await db.execute(
        select(User.username, Role.name, User.password_hash, User.must_change_password)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.builtin.is_(True))
        .order_by(User.username)
    )
    assert [tuple(row) for row in rows] == [
        ("admin", "admin", None, True),
        ("anonymous", "anonymous", None, False),
    ]


async def test_a_new_user_gets_an_id_and_timestamps_without_a_reload(db):
    user = User(username="dana", display_name="Dana")
    db.add(user)
    await db.flush()

    assert user.id is not None
    assert user.status == "active"
    assert user.created_at is not None
    assert user.created_at.tzinfo is not None
    assert user.updated_at == user.created_at or user.updated_at > user.created_at
