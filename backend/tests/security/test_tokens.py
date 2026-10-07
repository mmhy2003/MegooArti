import uuid
from datetime import timedelta

import pytest

from megooarti.errors import ApiError
from megooarti.security import tokens
from megooarti.security.models import User
from tests.security.conftest import NOW


async def make(db, user, name="ci", **fields):
    fields.setdefault("expires_at", None)
    fields.setdefault("scopes", None)
    return await tokens.create_token(db, user.id, name=name, **fields)


async def test_a_token_is_found_by_its_value_but_stores_only_a_hash(db, dana):
    token, value = await make(db, dana)

    assert value.startswith("mga_")
    assert token.display_prefix == value[:8]
    assert token.token_hash != value
    assert token.created_at is not None
    assert (await tokens.find_token(db, value, NOW)).id == token.id
    assert await tokens.find_token(db, "mga_" + "x" * 43, NOW) is None
    assert await tokens.find_token(db, "no-prefix", NOW) is None


async def test_an_expired_token_is_not_found(db, dana):
    _, value = await make(db, dana, expires_at=NOW + timedelta(days=1))

    assert await tokens.find_token(db, value, NOW)
    assert await tokens.find_token(db, value, NOW + timedelta(days=1)) is None


async def test_scopes_are_stored_as_given(db, dana):
    scoped, _ = await make(db, dana, name="scoped", scopes=["repository:*:*:read"])
    unscoped, _ = await make(db, dana, name="unscoped")

    assert scoped.scopes == ["repository:*:*:read"]
    assert unscoped.scopes is None


async def test_token_names_are_unique_per_user_only(db, dana):
    other = User(username="eli", display_name="Eli")
    db.add(other)
    await db.flush()
    await make(db, dana, name="ci")

    await make(db, other, name="ci")
    with pytest.raises(ApiError) as caught:
        await make(db, dana, name="ci")

    assert caught.value.code == "conflict"


async def test_list_is_newest_first_and_paged(db, dana):
    for name in ("one", "two", "three"):
        token, _ = await make(db, dana, name=name)
        token.created_at = NOW + timedelta(minutes=len(name))
    await db.flush()

    first, total = await tokens.list_tokens(db, dana.id, limit=2, offset=0)

    assert total == 3
    assert [token.name for token in first] == ["three", "one"]


async def test_revoke_removes_the_token(db, dana):
    token, value = await make(db, dana)

    await tokens.revoke_token(db, dana.id, token.id)

    assert await tokens.find_token(db, value, NOW) is None


@pytest.mark.parametrize("wrong", ["owner", "token"])
async def test_revoking_a_token_the_user_does_not_have_is_not_found(db, dana, wrong):
    token, _ = await make(db, dana)
    owner_id = uuid.uuid4() if wrong == "owner" else dana.id
    token_id = uuid.uuid4() if wrong == "token" else token.id

    with pytest.raises(ApiError) as caught:
        await tokens.revoke_token(db, owner_id, token_id)

    assert (caught.value.status_code, caught.value.code) == (404, "not_found")


async def test_touch_moves_last_used_at_most_once_a_minute(db, dana):
    token, _ = await make(db, dana)

    tokens.touch(token, NOW)
    tokens.touch(token, NOW + timedelta(seconds=59))
    assert token.last_used_at == NOW

    tokens.touch(token, NOW + timedelta(seconds=60))
    assert token.last_used_at == NOW + timedelta(seconds=60)
