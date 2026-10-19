"""The hourly check (spec 7, D4): a user of an LDAP source whose DN the directory no longer
has is disabled, their sessions ended and their tokens refused; nobody is disabled while
the directory cannot be asked, nor by a source that is off."""

from sqlalchemy import select

from megooarti.security import directory_check
from megooarti.security.models import User
from tests.accounts import bearer, sign_in

SESSION = "/api/v1/auth/session"


async def status_of(sessionmaker, username: str) -> str:
    async with sessionmaker() as db:
        return await db.scalar(select(User.status).where(User.username == username))


async def test_a_user_the_directory_no_longer_has_is_disabled_and_signed_out(
    app, client, other_client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password")
    directory.person("lou", "lou's password")
    await add_ldap_source()
    await sign_in(client, "kim", "kim's password")
    token = (await client.post("/api/v1/me/tokens", json={"name": "ci"})).json()["token"]
    await sign_in(other_client, "lou", "lou's password")

    directory.remove(kim)
    disabled = await directory_check.run(app)
    session = (await client.get(SESSION)).json()
    by_token = await client.get(SESSION, headers=bearer(token))

    assert disabled == 1
    assert await status_of(sessionmaker, "kim") == "disabled"
    assert await status_of(sessionmaker, "lou") == "active"
    assert session["authenticated"] is False
    assert by_token.status_code == 401
    assert (await other_client.get(SESSION)).json()["user"]["username"] == "lou"


async def test_a_directory_that_cannot_be_asked_disables_nobody(
    app, client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password")
    await add_ldap_source()
    await sign_in(client, "kim", "kim's password")

    directory.remove(kim)
    directory.down = True
    disabled = await directory_check.run(app)

    assert disabled == 0
    assert await status_of(sessionmaker, "kim") == "active"


async def test_a_source_that_is_off_is_not_checked(
    app, client, directory, add_ldap_source, change_source, sessionmaker
):
    kim = directory.person("kim", "kim's password")
    corp = await add_ldap_source()
    await sign_in(client, "kim", "kim's password")
    await change_source(corp, enabled=False)
    directory.binds.clear()

    directory.remove(kim)
    disabled = await directory_check.run(app)

    assert disabled == 0
    assert directory.binds == []
    assert await status_of(sessionmaker, "kim") == "active"


async def test_the_check_is_given_to_the_server_to_run_every_hour():
    assert directory_check.CHECK_SECONDS == 3600


async def test_a_users_base_the_directory_does_not_show_disables_nobody(
    app, client, directory, add_ldap_source, change_source, sessionmaker
):
    # An empty replica, or a bind DN that may no longer read: every DN would look gone.
    kim = directory.person("kim", "kim's password")
    corp = await add_ldap_source()
    await sign_in(client, "kim", "kim's password")

    await change_source(corp, user_base="ou=nowhere,dc=corp,dc=example")
    directory.remove(kim)
    disabled = await directory_check.run(app)

    assert disabled == 0
    assert await status_of(sessionmaker, "kim") == "active"


async def test_every_user_gone_at_once_disables_nobody_and_is_logged(
    app, client, other_client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password")
    lou = directory.person("lou", "lou's password")
    await add_ldap_source()
    await sign_in(client, "kim", "kim's password")
    await sign_in(other_client, "lou", "lou's password")

    directory.remove(kim)
    directory.remove(lou)
    disabled = await directory_check.run(app)

    assert disabled == 0
    assert await status_of(sessionmaker, "kim") == "active"


async def test_a_user_the_filter_no_longer_gives_is_disabled(
    app, client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password", employeeType="staff")
    directory.person("lou", "lou's password", employeeType="staff")
    await add_ldap_source(user_filter="(&(uid={username})(employeeType=staff))")
    await sign_in(client, "kim", "kim's password")

    directory.remove(kim)
    directory.person("kim", "kim's password", employeeType="former")
    disabled = await directory_check.run(app)

    assert disabled == 1
    assert await status_of(sessionmaker, "kim") == "disabled"


async def test_a_directory_that_fails_mid_check_leaves_the_next_source_checked(
    app, client, other_client, directory, add_ldap_source, sessionmaker, monkeypatch
):
    from megooarti.security import ldap

    kim = directory.person("kim", "kim's password")
    directory.person("lou", "lou's password")
    await add_ldap_source("First")
    await add_ldap_source("Second")
    await sign_in(client, "kim", "kim's password")
    missing = ldap.missing
    calls = []

    def failing_first(settings, context, dns):
        calls.append(len(calls))
        if len(calls) == 1:
            raise ConnectionResetError("the directory went away")
        return missing(settings, context, dns)

    monkeypatch.setattr(ldap, "missing", failing_first)
    directory.remove(kim)
    disabled = await directory_check.run(app)  # a failure is one source's, not the run's

    assert (disabled, calls) == (0, [0])
    assert await status_of(sessionmaker, "kim") == "active"
