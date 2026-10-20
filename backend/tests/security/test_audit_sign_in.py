"""Sign-in in the audit log (spec 9): every one that succeeds, fails, is throttled or is
refused, by every source, kept though the request that failed is answered with an error;
and every sign-out."""

from tests.accounts import PASSWORD, basic, bearer, sign_in
from tests.audit import last, records
from tests.security.test_oidc_sign_in import landed, oidc_path
from tests.security.test_oidc_sign_in import sign_in as oidc_sign_in

SESSION = "/api/v1/auth/session"
LOGIN = "/api/v1/auth/login"


async def test_a_sign_in_and_a_sign_out_are_recorded(client, make_user, sessionmaker):
    await make_user("kim")

    await sign_in(client, "kim")
    await client.post("/api/v1/auth/logout")

    signed_in = await last(sessionmaker, "sign_in.succeeded")
    signed_out = await last(sessionmaker, "session.signed_out")
    assert (signed_in.actor, signed_in.method, signed_in.target_name) == ("kim", "session", "kim")
    assert signed_in.address == "127.0.0.1"
    assert signed_in.changes is None  # one of MegooArti's own: no source
    assert (signed_out.actor, signed_out.target_name) == ("kim", "kim")


async def test_a_wrong_password_is_recorded_though_the_request_fails(
    client, make_user, sessionmaker
):
    await make_user("kim")

    refused = await client.post(LOGIN, json={"username": "kim", "password": "wrong"})
    by_basic = await client.get(SESSION, headers=basic("Kim", "wrong"))

    failed = await records(sessionmaker, "sign_in.failed")
    assert (refused.status_code, by_basic.status_code) == (401, 401)
    assert [(entry.actor, entry.target_name) for entry in failed] == [
        (None, "kim"),
        (None, "kim"),
    ]


async def test_a_token_that_is_none_is_recorded_without_a_name(client, sessionmaker):
    await client.get(SESSION, headers=bearer("mga_" + "x" * 40))

    failed = await last(sessionmaker, "sign_in.failed")
    assert (failed.target_kind, failed.target_name) == (None, None)


async def test_a_throttled_sign_in_is_recorded(client, make_user, sessionmaker):
    await make_user("kim")
    for _ in range(5):
        await client.post(LOGIN, json={"username": "kim", "password": "wrong"})

    throttled = await client.post(LOGIN, json={"username": "kim", "password": PASSWORD})

    assert throttled.status_code == 429
    assert (await last(sessionmaker, "sign_in.throttled")).target_name == "kim"


async def test_a_directorys_sign_in_says_its_source_and_a_wrong_password_there_too(
    client, other_client, directory, add_ldap_source, sessionmaker
):
    directory.person("kim", "kim's password")
    await add_ldap_source()

    await sign_in(client, "kim", "kim's password")
    await other_client.get(SESSION, headers=basic("kim", "not kim's"))

    signed_in = await last(sessionmaker, "sign_in.succeeded")
    assert signed_in.changes == {"source": {"before": None, "after": "Corp LDAP"}}
    assert (await last(sessionmaker, "sign_in.failed")).target_name == "kim"


async def test_a_providers_sign_in_is_recorded_and_one_that_failed_says_why(
    client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source()
    provider.person("kim")

    landed(await oidc_sign_in(client, provider, source, "kim"))
    started = await client.get(oidc_path(source, "start"), params={"next": "/search"})
    code = provider.authorize(started.headers["location"], "kim")
    await client.get(oidc_path(source, "callback"), params={"code": code, "state": "forged"})

    signed_in = await last(sessionmaker, "sign_in.succeeded")
    failed = await last(sessionmaker, "sign_in.failed")
    assert (signed_in.actor, signed_in.target_name) == ("kim", "kim")
    assert signed_in.changes == {"source": {"before": None, "after": "Corp SSO"}}
    assert failed.target_name == "Corp SSO"
    assert failed.changes["why"] == {"before": None, "after": "failed"}


async def test_a_trusted_header_from_elsewhere_is_recorded_as_refused(
    admin_client, other_client, sessionmaker
):
    await admin_client.post(
        "/api/v1/auth-sources",
        json={"kind": "header", "name": "Corp SSO proxy", "enabled": True, "settings": {}},
    )

    refused = await other_client.get(SESSION, headers={"X-Forwarded-User": "admin"})

    said = await last(sessionmaker, "sign_in.refused")
    assert refused.status_code == 401
    assert (said.target_kind, said.target_name) == ("source", "Corp SSO proxy")
    assert said.changes == {"why": {"before": None, "after": "not through a trusted proxy"}}


async def test_a_blocked_address_is_recorded_once_not_at_every_attempt(
    client, make_user, sessionmaker
):
    await make_user("kim")
    for _ in range(5):
        await client.post(LOGIN, json={"username": "kim", "password": "wrong"})

    for _ in range(4):
        await client.post(LOGIN, json={"username": "kim", "password": PASSWORD})

    assert len(await records(sessionmaker, "sign_in.failed")) == 5
    assert len(await records(sessionmaker, "sign_in.throttled")) == 1


async def test_refusals_nobody_signed_in_for_are_recorded_once_a_minute_from_an_address(
    admin_client, other_client, sessionmaker
):
    await admin_client.post(
        "/api/v1/auth-sources",
        json={"kind": "header", "name": "Corp SSO proxy", "enabled": True, "settings": {}},
    )
    nowhere = "/api/v1/auth/oidc/00000000-0000-0000-0000-000000000000/callback"

    for _ in range(3):
        await other_client.get(SESSION, headers={"X-Forwarded-User": "admin"})
        await other_client.get(nowhere, params={"code": "x", "state": "y"})

    assert len(await records(sessionmaker, "sign_in.refused")) == 1
    assert len(await records(sessionmaker, "sign_in.failed")) == 1
