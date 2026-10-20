"""What the security routes write to the audit log (spec 9): every change of users,
roles, tokens, sources, settings and certificates, by whom, with what changed, and never
a secret; and what the server changes itself, as the system."""

from sqlalchemy import select

from megooarti.security import directory_check, roles
from megooarti.security.models import User
from tests.accounts import PASSWORD, basic, sign_in
from tests.audit import last, records
from tests.tls import authority

USERS = "/api/v1/users"
ROLES = "/api/v1/roles"
SOURCES = "/api/v1/auth-sources"
SETTINGS = "/api/v1/settings"


async def user_id(sessionmaker, username: str) -> str:
    async with sessionmaker() as db:
        return str(await db.scalar(select(User.id).where(User.username == username)))


async def test_a_user_made_changed_and_deleted_is_recorded_with_what_changed(
    admin_client, sessionmaker
):
    made = await admin_client.post(
        USERS,
        json={"username": "kim", "display_name": "Kim", "password": PASSWORD, "roles": []},
    )
    kim = made.json()["id"]
    await admin_client.patch(f"{USERS}/{kim}", json={"email": "kim@corp.example"})
    await admin_client.put(f"{USERS}/{kim}/password", json={"password": "another one entirely"})
    await admin_client.delete(f"{USERS}/{kim}")

    created = await last(sessionmaker, "user.created")
    updated = await last(sessionmaker, "user.updated")
    password = await last(sessionmaker, "user.password_changed")
    deleted = await last(sessionmaker, "user.deleted")
    assert (created.actor, created.method, created.target_name) == ("root", "session", "kim")
    assert created.changes["display_name"] == {"before": None, "after": "Kim"}
    assert "id" not in created.changes and "password" not in created.changes
    assert updated.changes == {"email": {"before": None, "after": "kim@corp.example"}}
    assert password.changes == {"password": {"before": "[redacted]", "after": "[redacted]"}}
    assert deleted.changes["username"] == {"before": "kim", "after": None}


async def test_a_change_that_is_refused_leaves_no_record(admin_client, sessionmaker):
    root = await user_id(sessionmaker, "root")

    refused = await admin_client.patch(f"{USERS}/{root}", json={"status": "disabled"})

    assert refused.status_code == 409
    assert await records(sessionmaker, "user.updated") == []


async def test_ones_own_password_and_tokens_are_recorded(client, make_user, sessionmaker):
    await make_user("kim")
    await sign_in(client, "kim")

    await client.put(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "another one entirely"},
    )
    token = (
        await client.post(
            "/api/v1/me/tokens", json={"name": "ci", "scopes": ["repository:*:*:read"]}
        )
    ).json()
    await client.delete(f"/api/v1/me/tokens/{token['id']}")

    password = await last(sessionmaker, "user.password_changed")
    created = await last(sessionmaker, "token.created")
    revoked = await last(sessionmaker, "token.revoked")
    assert (password.actor, password.target_name) == ("kim", "kim")
    assert (created.target_kind, created.target_name) == ("token", "kim/ci")
    assert created.changes == {"scopes": {"before": None, "after": ["repository:*:*:read"]}}
    assert (revoked.actor, revoked.target_name) == ("kim", "kim/ci")
    assert token["token"] not in str(created.changes)


async def test_an_administrator_revoking_someones_token_is_recorded(
    admin_client, make_user, make_token, sessionmaker
):
    kim = await make_user("kim")
    await make_token(kim, "deploy")
    listed = await admin_client.get(f"{USERS}/{kim.id}/tokens")

    await admin_client.delete(f"{USERS}/{kim.id}/tokens/{listed.json()['items'][0]['id']}")

    revoked = await last(sessionmaker, "token.revoked")
    assert (revoked.actor, revoked.target_name) == ("root", "kim/deploy")


async def test_a_role_made_changed_and_deleted_is_recorded(admin_client, sessionmaker):
    role = {"name": "developers", "description": "", "permissions": [], "roles": []}
    await admin_client.post(ROLES, json=role)
    await admin_client.put(
        f"{ROLES}/developers",
        json={"description": "Devs", "permissions": ["repository:*:*:read"], "roles": []},
    )
    await admin_client.delete(f"{ROLES}/developers")

    updated = await last(sessionmaker, "role.updated")
    assert (await last(sessionmaker, "role.created")).target_name == "developers"
    assert updated.changes == {
        "description": {"before": "", "after": "Devs"},
        "permissions": {"before": [], "after": ["repository:*:*:read"]},
    }
    assert (await last(sessionmaker, "role.deleted")).target_name == "developers"


async def test_a_sources_secret_is_said_by_its_name_and_never_its_value(admin_client, sessionmaker):
    source = {
        "kind": "oidc",
        "name": "Corp SSO",
        "settings": {
            "issuer": "https://sso.corp.example",
            "client_id": "megooarti",
            "client_secret": "s3cr3t-value",
        },
    }
    made = (await admin_client.post(SOURCES, json=source)).json()
    await admin_client.put(
        f"{SOURCES}/{made['id']}",
        json={
            "name": "Corp SSO",
            "enabled": True,
            "settings": {**source["settings"], "client_secret": "an0ther-value"},
        },
    )
    await admin_client.delete(f"{SOURCES}/{made['id']}")

    created = await last(sessionmaker, "source.created")
    updated = await last(sessionmaker, "source.updated")
    every = str([entry.changes for entry in await records(sessionmaker)])
    assert created.changes["client_secret"] == {"before": "[redacted]", "after": "[redacted]"}
    assert created.changes["kind"] == {"before": None, "after": "oidc"}
    assert updated.changes["enabled"] == {"before": False, "after": True}
    assert updated.changes["client_secret"] == {"before": "[redacted]", "after": "[redacted]"}
    assert (await last(sessionmaker, "source.deleted")).target_name == "Corp SSO"
    assert "s3cr3t-value" not in every and "an0ther-value" not in every


async def test_the_sources_order_is_recorded_as_a_setting(admin_client, sessionmaker):
    ids = []
    for name in ("First", "Second"):
        made = await admin_client.post(
            SOURCES, json={"kind": "header", "name": name, "settings": {}}
        )
        ids.append(made.json()["id"])

    await admin_client.put(f"{SOURCES}/order", json={"ids": list(reversed(ids))})

    ordered = await last(sessionmaker, "setting.changed")
    assert ordered.target_name == "source_order"
    assert ordered.changes == {
        "source_order": {"before": ["First", "Second"], "after": ["Second", "First"]}
    }


async def test_every_setting_changed_is_recorded_and_one_left_as_it_was_is_not(
    admin_client, sessionmaker
):
    await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": "https://repo.example"})
    await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": True})
    await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": True})
    await admin_client.put(f"{SETTINGS}/default-role", json={"default_role": "admin"})
    await admin_client.put(f"{SETTINGS}/trusted-proxies", json={"trusted_proxies": ["10.0.0.5"]})

    changed = {
        entry.target_name: entry.changes for entry in await records(sessionmaker, "setting.changed")
    }
    assert len(await records(sessionmaker, "setting.changed")) == 4
    assert changed["base_url"] == {"base_url": {"before": None, "after": "https://repo.example"}}
    assert changed["anonymous_access"] == {
        "anonymous_access": {"before": {"enabled": False}, "after": {"enabled": True}}
    }
    assert changed["default_role"] == {"default_role": {"before": None, "after": "admin"}}
    assert changed["trusted_proxies"] == {
        "trusted_proxies": {"before": [], "after": ["10.0.0.5/32"]}
    }


async def test_a_certificate_trusted_and_removed_is_recorded_by_its_fingerprint(
    admin_client, sessionmaker
):
    ca = authority("Corp Root CA")
    added = (await admin_client.post("/api/v1/certificates", json={"pem": ca.pem})).json()
    await admin_client.delete(f"/api/v1/certificates/{added['id']}")

    trusted = await last(sessionmaker, "certificate.trusted")
    removed = await last(sessionmaker, "certificate.removed")
    assert trusted.target_name == added["subject"]
    assert trusted.changes["fingerprint"] == {"before": None, "after": added["fingerprint"]}
    assert "pem" not in trusted.changes
    assert removed.changes["fingerprint"] == {"before": added["fingerprint"], "after": None}


async def test_a_request_signed_in_by_password_is_recorded_so(client, make_user, sessionmaker):
    await make_user("ada", roles=["admin"])

    await client.post(
        ROLES,
        json={"name": "ops", "description": "", "permissions": [], "roles": []},
        headers=basic("ada", PASSWORD),
    )

    made = await last(sessionmaker, "role.created")
    assert (made.actor, made.method) == ("ada", "password")


async def test_a_user_the_directory_no_longer_has_is_disabled_by_the_system(
    app, client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password")
    directory.person("lou", "lou's password")
    await add_ldap_source()
    await sign_in(client, "kim", "kim's password")
    await sign_in(client, "lou", "lou's password")

    directory.remove(kim)
    await directory_check.run(app)

    disabled = await last(sessionmaker, "user.updated")
    assert (disabled.actor, disabled.method, disabled.target_name) == (None, "system", "kim")
    assert disabled.changes["status"] == {"before": "active", "after": "disabled"}


async def test_a_first_sign_in_and_the_roles_groups_give_are_recorded(
    admin_client, other_client, sessionmaker
):
    async with sessionmaker() as db:
        await roles.create_role(db, "developers", "", ["repository:*:*:read"], [])
        await db.commit()
    await admin_client.post(
        SOURCES,
        json={
            "kind": "header",
            "name": "Corp SSO proxy",
            "enabled": True,
            "settings": {"groups_header": "X-Forwarded-Groups"},
            "group_mapping": [{"group": "developers", "roles": ["developers"]}],
        },
    )
    await admin_client.put(f"{SETTINGS}/trusted-proxies", json={"trusted_proxies": ["10.0.0.5"]})
    proxied = {"X-Forwarded-For": "198.51.100.9, 10.0.0.5", "X-Forwarded-User": "kim"}

    await other_client.get(
        "/api/v1/auth/session", headers={**proxied, "X-Forwarded-Groups": "developers"}
    )
    await other_client.get(
        "/api/v1/auth/session", headers={**proxied, "X-Forwarded-Groups": "developers"}
    )
    await other_client.get("/api/v1/auth/session", headers={**proxied, "X-Forwarded-Groups": ""})

    made = await last(sessionmaker, "user.created")
    mapped = [entry.changes for entry in await records(sessionmaker, "user.updated")]
    assert (made.target_name, made.address) == ("kim", "198.51.100.9")
    assert made.changes == {"source": {"before": None, "after": "Corp SSO proxy"}}
    assert mapped == [
        {"roles_from_groups": {"before": [], "after": ["developers"]}},
        {"roles_from_groups": {"before": ["developers"], "after": []}},
    ]


async def test_the_default_role_cleared_with_its_role_is_recorded_as_a_setting(
    admin_client, sessionmaker
):
    await admin_client.post(
        ROLES, json={"name": "everyone", "description": "", "permissions": [], "roles": []}
    )
    await admin_client.put(f"{SETTINGS}/default-role", json={"default_role": "everyone"})

    await admin_client.delete(f"{ROLES}/everyone")

    cleared = await last(sessionmaker, "setting.changed")
    assert cleared.changes == {"default_role": {"before": "everyone", "after": None}}
