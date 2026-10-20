import pytest

from megooarti.system.settings_store import DEFAULTS, get_setting, set_setting


async def test_defaults_apply_when_nothing_is_stored(db):
    assert await get_setting(db, "base_url") is None
    assert await get_setting(db, "anonymous_access") == {"enabled": False}
    assert await get_setting(db, "default_role") is None
    assert await get_setting(db, "local_sign_in") == {"enabled": True}
    assert await get_setting(db, "trusted_proxies") == []
    assert await get_setting(db, "audit_retention_days") == 365
    assert set(DEFAULTS) == {
        "base_url",
        "anonymous_access",
        "default_role",
        "local_sign_in",
        "trusted_proxies",
        "audit_retention_days",
    }


async def test_a_stored_value_replaces_the_default(db):
    await set_setting(db, "base_url", "https://repo.example.org")
    await set_setting(db, "anonymous_access", {"enabled": True})

    assert await get_setting(db, "base_url") == "https://repo.example.org"
    assert await get_setting(db, "anonymous_access") == {"enabled": True}


async def test_a_value_can_be_overwritten(db):
    await set_setting(db, "base_url", "https://one.example.org")
    await set_setting(db, "base_url", "https://two.example.org")

    assert await get_setting(db, "base_url") == "https://two.example.org"


async def test_none_restores_the_default(db):
    await set_setting(db, "base_url", "https://repo.example.org")
    await set_setting(db, "base_url", None)
    await set_setting(db, "base_url", None)

    assert await get_setting(db, "base_url") is None


async def test_unknown_keys_are_a_programming_error(db):
    with pytest.raises(KeyError):
        await get_setting(db, "no_such_setting")
    with pytest.raises(KeyError):
        await set_setting(db, "no_such_setting", 1)
