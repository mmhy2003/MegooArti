"""LDAP sources (spec 7): their settings checked, a person signed in by binding as their
entry, their groups read from `memberOf` or a search, Test, and TLS that trusts what the
server trusts in a context of its own."""

import asyncio

import pytest
from sqlalchemy import select

from megooarti.repositories import remote
from megooarti.security import ldap, roles, sources
from megooarti.security.models import User
from tests.accounts import basic, error_code
from tests.security.ldap_directory import BASE, GROUPS, PEOPLE, READER, READER_PASSWORD
from tests.tls import authority, https_server

SOURCES = "/api/v1/auth-sources"
LOGIN = "/api/v1/auth/login"
SESSION = "/api/v1/auth/session"
DEVELOPERS = [{"group": "developers", "roles": ["developers"]}]


def ldap_source(name: str = "Corp LDAP", **settings) -> dict:
    return {
        "kind": "ldap",
        "name": name,
        "settings": {
            "url": "ldap://ldap.corp.example",
            "bind_dn": READER,
            "bind_password": READER_PASSWORD,
            "user_base": PEOPLE,
            **settings,
        },
    }


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def stored(sessionmaker, username: str) -> User | None:
    async with sessionmaker() as db:
        return await db.scalar(select(User).where(User.username == username))


async def login(client, username: str, password: str):
    return await client.post(LOGIN, json={"username": username, "password": password})


# --- Settings -----------------------------------------------------------------------------


async def test_an_ldap_source_is_kept_with_its_defaults_and_its_password_sealed(admin_client):
    made = await admin_client.post(SOURCES, json=ldap_source(starttls=True))

    assert made.status_code == 201, made.text
    assert made.json()["settings"] == {
        "url": "ldap://ldap.corp.example",
        "starttls": True,
        "bind_dn": READER,
        "user_base": PEOPLE,
        "user_filter": "(uid={username})",
        "groups": "member_of",
        "username_attribute": "uid",
        "name_attribute": "cn",
        "email_attribute": "mail",
        "member_of_attribute": "memberOf",
        "group_name_attribute": "cn",
    }
    assert made.json()["secrets"] == ["bind_password"]
    assert READER_PASSWORD not in made.text
    assert made.json()["redirect_uri"] is None


@pytest.mark.parametrize(
    ("sent", "field"),
    [
        ({"url": "https://ldap.corp.example"}, "settings.url"),
        ({"url": "ldap://"}, "settings.url"),
        ({"url": "ldap://ldap.corp.example/ou=people"}, "settings.url"),
        ({"url": "ldap://ldap.corp.example:port"}, "settings.url"),
        ({"url": "ldaps://ldap.corp.example", "starttls": True}, "settings.starttls"),
        ({"user_base": ""}, "settings.user_base"),
        ({"user_base": "not a dn"}, "settings.user_base"),
        ({"bind_dn": "not a dn"}, "settings.bind_dn"),
        ({"user_filter": "uid={username}"}, "settings.user_filter"),
        ({"user_filter": "(uid=kim)"}, "settings.user_filter"),
        ({"user_filter": "(&(uid={username})"}, "settings.user_filter"),
        ({"user_filter": "(uid={user})"}, "settings.user_filter"),
        ({"groups": "everything"}, "settings.groups"),
        ({"groups": "search"}, "settings.group_base"),
        (
            {"groups": "search", "group_base": GROUPS, "group_filter": "(cn=x)"},
            "settings.group_filter",
        ),
        ({"email_attribute": "mail address"}, "settings.email_attribute"),
    ],
)
async def test_what_is_wrong_with_an_ldap_source_is_said_where_it_is(admin_client, sent, field):
    refused = await admin_client.post(SOURCES, json=ldap_source(**sent))

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_active_directory_binds_with_a_user_principal_name(admin_client):
    made = await admin_client.post(
        SOURCES,
        json=ldap_source(
            bind_dn="svc-megooarti@corp.example",
            user_filter="(sAMAccountName={username})",
            username_attribute="sAMAccountName",
            name_attribute="displayName",
        ),
    )

    assert made.status_code == 201, made.text
    assert made.json()["settings"]["bind_dn"] == "svc-megooarti@corp.example"


async def test_the_bind_password_is_asked_again_for_another_server_or_without_starttls(
    admin_client,
):
    made = (await admin_client.post(SOURCES, json=ldap_source(starttls=True))).json()

    for changed in ({"url": "ldap://attacker.example"}, {"starttls": False}):
        refused = await admin_client.put(
            f"{SOURCES}/{made['id']}",
            json={"name": made["name"], "settings": {**made["settings"], **changed}},
        )
        assert refused.json()["error"]["details"][0]["field"] == "settings.bind_password", changed


# --- Signing in ---------------------------------------------------------------------------


async def test_a_person_signs_in_with_their_directory_password_and_their_groups_roles(
    client, directory, add_ldap_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    developers = f"cn=developers,{GROUPS}"
    kim = directory.person(
        "kim", "kim's password", cn="Kim Lee", mail="kim@corp.example", memberOf=[developers]
    )
    await add_ldap_source(mapping=DEVELOPERS)

    signed_in = await login(client, "kim", "kim's password")
    stored_kim = await stored(sessionmaker, "kim")

    assert signed_in.status_code == 200, signed_in.text
    assert "repository:*:*:read" in signed_in.json()["permissions"]
    assert (stored_kim.external_id, stored_kim.display_name, stored_kim.email) == (
        kim,
        "Kim Lee",
        "kim@corp.example",
    )
    assert directory.binds == [READER, kim]  # the bind DN, then the person's own entry


async def test_groups_are_found_by_a_search_and_mapped_by_name_or_dn(
    client, directory, add_ldap_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    await make_role(sessionmaker, "auditors", "admin:users:read")
    lou = directory.person("lou", "lou's password")
    directory.group("developers", lou)
    auditors = directory.group("auditors", lou)
    await add_ldap_source(
        groups="search",
        group_base=GROUPS,
        mapping=[*DEVELOPERS, {"group": auditors.upper(), "roles": ["auditors"]}],
    )

    signed_in = await login(client, "lou", "lou's password")

    assert signed_in.status_code == 200, signed_in.text
    assert {"repository:*:*:read", "admin:users:read"} <= set(signed_in.json()["permissions"])


async def test_a_wrong_password_is_refused_and_no_other_source_is_asked(
    client, directory, add_ldap_source, add_source
):
    directory.person("kim", "kim's password")
    await add_ldap_source()
    await add_source("after", {"kim": {"password": "wrong", "groups": []}})

    refused = await login(client, "kim", "wrong")

    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


async def test_an_empty_password_is_refused_before_the_directory_is_asked(
    client, directory, add_ldap_source
):
    directory.person("kim", "kim's password")
    await add_ldap_source()

    refused = await client.get(SESSION, headers=basic("kim", ""))

    assert refused.status_code == 401
    assert directory.binds == []


@pytest.mark.parametrize("name", ["*", "*)(uid=*", "kim)(|(uid=*", "\\2a"])
async def test_a_name_is_never_part_of_the_filter(client, directory, add_ldap_source, name):
    directory.person("kim", "kim's password")
    await add_ldap_source()

    refused = await client.get(SESSION, headers=basic(name, "kim's password"))

    assert refused.status_code == 401
    assert directory.binds == [READER]  # nobody was found to bind as


async def test_a_name_that_several_entries_have_signs_nobody_in(client, directory, add_ldap_source):
    directory.add(f"ou=staff,{BASE}", objectClass="organizationalUnit", ou="staff")
    directory.person("sam", "sam's password")
    directory.person("sam", "sam's password", ou="staff")
    await add_ldap_source(user_base=BASE)

    refused = await login(client, "sam", "sam's password")

    assert refused.status_code == 401


async def test_a_directory_down_or_refusing_the_bind_dn_is_named(
    client, directory, add_ldap_source
):
    directory.person("kim", "kim's password")
    await add_ldap_source(bind_password="not the reader's password")

    refused_bind = await login(client, "kim", "kim's password")
    directory.down = True
    down = await login(client, "kim", "kim's password")

    for answer in (refused_bind, down):
        assert (answer.status_code, error_code(answer)) == (503, "source_unavailable")


async def test_testing_a_source_finds_a_person_and_their_groups_without_their_password(
    admin_client, directory, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    developers = f"cn=developers,{GROUPS}"
    kim = directory.person("kim", "kim's password", cn="Kim Lee", memberOf=[developers])
    made = (
        await admin_client.post(SOURCES, json={**ldap_source(), "group_mapping": DEVELOPERS})
    ).json()

    bare = (await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})).json()
    found = (
        await admin_client.post(f"{SOURCES}/{made['id']}/test", json={"username": "kim"})
    ).json()
    nobody = (
        await admin_client.post(f"{SOURCES}/{made['id']}/test", json={"username": "ann"})
    ).json()

    assert bare == {
        "ok": True,
        "message": "The directory answered, and took the bind DN.",
        "user": None,
    }
    assert (found["ok"], found["message"]) == (True, f"kim is {kim}.")
    assert (found["user"]["display_name"], found["user"]["roles"]) == ("Kim Lee", ["developers"])
    assert (nobody["ok"], nobody["user"]) == (False, None)
    assert kim not in directory.binds  # no password was tried


# --- TLS ----------------------------------------------------------------------------------


async def test_ldaps_trusts_the_added_certificates_in_a_context_of_its_own(app):
    ca = authority()
    remote.trust(app, [ca.pem])
    shared = remote.tls_of(app)
    reach = sources.outbound(app)
    async with https_server(ca) as port:
        settings = {
            "url": f"ldaps://127.0.0.1:{port}",
            "starttls": False,
            "bind_dn": None,
            "bind_password": None,
        }
        untrusted = ldap.context_for(())
        trusted = ldap.context_for(reach.trusted)
        with pytest.raises(sources.SourceUnavailable) as refused:
            await asyncio.to_thread(ldap._bound, settings, untrusted)
        with pytest.raises(sources.SourceUnavailable) as past_tls:
            await asyncio.to_thread(ldap._bound, settings, trusted)
    await remote.close_clients(app)

    assert "CERTIFICATE_VERIFY_FAILED" in str(refused.value)
    # Through TLS: what fails then is that an HTTPS server does not speak LDAP.
    assert "CERTIFICATE_VERIFY_FAILED" not in str(past_tls.value)
    assert trusted is not shared and shared is remote.tls_of(app)


# --- The final review's ---------------------------------------------------------------------


def wire(**answer):
    from tests.security.ldap_wire import WireDirectory

    return WireDirectory(**answer)


async def test_a_referral_is_not_followed_with_the_bind_password():
    # Active Directory refers a base outside its forest to another server: the bind DN's
    # password must not go there, in the clear or at all.
    from tests.security.ldap_wire import settings_for

    elsewhere = wire()
    with elsewhere.serving() as other:
        referring = wire(search_code=10, referral=f"ldap://127.0.0.1:{other}/dc=elsewhere")
        with referring.serving() as port:
            settings = settings_for(port)
            with pytest.raises(sources.SourceUnavailable) as signing_in:
                await asyncio.to_thread(
                    ldap._sign_in, settings, ldap.context_for(()), "kim", "pw", None
                )
            with pytest.raises(sources.SourceUnavailable):
                await asyncio.to_thread(
                    ldap.missing, settings, ldap.context_for(()), [f"uid=kim,{PEOPLE}"]
                )

    assert elsewhere.binds == []
    assert "referral" in str(signing_in.value).lower()


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        ({"search_code": 51}, "busy"),
        ({"search_code": 50}, "insufficientAccessRights"),
        ({"search_code": 1}, "operationsError"),
        ({"drop_on_search": True}, "could not be reached"),
    ],
    ids=["busy", "no-rights", "operations-error", "dropped"],
)
async def test_a_search_that_fails_is_a_directory_unavailable_never_nobody(answer, said):
    # "Nobody" would send the password on to the next source (S5), and say a wrong thing.
    from tests.security.ldap_wire import settings_for

    with wire(**answer).serving() as port:
        settings = settings_for(port)
        with pytest.raises(sources.SourceUnavailable) as signing_in:
            await asyncio.to_thread(
                ldap._sign_in, settings, ldap.context_for(()), "kim", "pw", None
            )
        with pytest.raises(sources.SourceUnavailable):
            await asyncio.to_thread(ldap._test, settings, ldap.context_for(()), "kim")

    assert said in str(signing_in.value)


async def test_a_known_user_signs_in_only_while_the_filter_still_gives_them(
    client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password", employeeType="staff")
    await add_ldap_source(user_filter="(&(uid={username})(employeeType=staff))")
    first = await login(client, "kim", "kim's password")

    directory.remove(kim)
    directory.person("kim", "kim's password", employeeType="former")
    again = await login(client, "kim", "kim's password")

    assert first.status_code == 200
    assert again.status_code == 401


async def test_a_known_user_outside_the_users_base_is_signed_in_no_more(
    client, directory, add_ldap_source, change_source, sessionmaker
):
    directory.add(f"ou=staff,{BASE}", objectClass="organizationalUnit", ou="staff")
    directory.person("kim", "kim's password")
    corp = await add_ldap_source(user_base=BASE)
    await login(client, "kim", "kim's password")

    await change_source(corp, user_base=f"ou=staff,{BASE}")
    again = await login(client, "kim", "kim's password")

    assert again.status_code == 401


async def test_a_group_search_that_fails_takes_no_role_away(
    client, directory, add_ldap_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    kim = directory.person("kim", "kim's password")
    directory.group("developers", kim)
    corp = await add_ldap_source(groups="search", group_base=GROUPS, mapping=DEVELOPERS)
    await login(client, "kim", "kim's password")

    async with sessionmaker() as db:
        from megooarti.security.models import AuthSource

        stored_source = await db.get(AuthSource, corp.id)
        stored_source.settings = {**stored_source.settings, "group_base": f"ou=gone,{BASE}"}
        await db.commit()
    again = await login(client, "kim", "kim's password")

    assert (again.status_code, error_code(again)) == (503, "source_unavailable")


async def test_the_group_filter_is_given_the_directorys_name_not_the_one_typed(
    client, directory, add_ldap_source, sessionmaker
):
    # People sign in with their email; groups name them by their uid.
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    directory.person("kim", "kim's password", mail="kim@corp.example")
    directory.add(
        f"cn=developers,{GROUPS}", objectClass="posixGroup", cn="developers", memberUid=["kim"]
    )
    await add_ldap_source(
        user_filter="(mail={username})",
        groups="search",
        group_base=GROUPS,
        group_filter="(memberUid={username})",
        mapping=DEVELOPERS,
    )

    signed_in = await login(client, "kim@corp.example", "kim's password")

    assert signed_in.status_code == 200, signed_in.text
    assert "repository:*:*:read" in signed_in.json()["permissions"]


async def test_a_directory_is_asked_on_threads_of_its_own(
    client, directory, add_ldap_source, monkeypatch
):
    # A slow directory must not take the threads files are read and written with.
    import threading

    seen = []
    signing_in = ldap._sign_in

    def recorded(*arguments):
        seen.append(threading.current_thread().name)
        return signing_in(*arguments)

    monkeypatch.setattr(ldap, "_sign_in", recorded)
    directory.person("kim", "kim's password")
    await add_ldap_source()

    await login(client, "kim", "kim's password")

    assert seen and all(name.startswith("ldap") for name in seen)
    assert ldap.THREADS._max_workers == ldap.THREAD_COUNT
