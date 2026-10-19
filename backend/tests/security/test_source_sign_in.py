"""Signing in through a source (spec 4.2, E2-E4): the user made at the first sign-in and
brought up to date at each, the order sources are asked in, and a source turned off."""

from sqlalchemy import select

from megooarti.security import roles, users
from megooarti.security.models import User, UserRole
from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in
from tests.security.directory import person

LOGIN = "/api/v1/auth/login"
SESSION = "/api/v1/auth/session"
DEVELOPERS = [{"group": "developers", "roles": ["developers"]}]


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def stored(sessionmaker, username: str) -> tuple[User | None, dict[str, str]]:
    """The user of this name, and the roles they hold, each with who gave it."""
    async with sessionmaker() as db:
        user = await users.get_user_by_username(db, username)
        if user is None:
            return None, {}
        held = await db.execute(
            select(roles.Role.name, UserRole.granted_by)
            .join(UserRole, UserRole.role_id == roles.Role.id)
            .where(UserRole.user_id == user.id)
        )
        return user, {name: by for name, by in held}


async def login(client, username: str, password: str):
    return await client.post(LOGIN, json={"username": username, "password": password})


async def test_the_first_sign_in_makes_the_user_with_the_roles_of_their_groups(
    client, add_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    corp = await add_source(
        "Corp",
        {
            "Carol": person(
                "carols secret",
                "Developers",
                display_name="Carol Danvers",
                email="carol@corp.example",
            )
        },
        mapping=DEVELOPERS,
    )

    signed_in = await login(client, "Carol", "carols secret")
    carol, held = await stored(sessionmaker, "carol")

    assert signed_in.status_code == 200, signed_in.text
    assert "repository:*:*:read" in signed_in.json()["permissions"]
    assert (carol.source_id, carol.external_id) == (corp.id, "uid=Carol,ou=people")
    assert (carol.display_name, carol.email, carol.password_hash) == (
        "Carol Danvers",
        "carol@corp.example",
        None,
    )
    assert carol.last_login_at is not None
    assert held == {"developers": "source"}  # groups are matched whatever their case


async def test_each_sign_in_brings_the_user_up_to_date_and_keeps_an_administrators_roles(
    admin_client, other_client, add_source, change_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    await make_role(sessionmaker, "auditors", "admin:users:read")
    corp = await add_source("corp", {"carol": person("pw", "developers")}, mapping=DEVELOPERS)
    await login(other_client, "carol", "pw")
    carol, _ = await stored(sessionmaker, "carol")
    await admin_client.patch(
        f"/api/v1/users/{carol.id}", json={"roles": ["developers", "auditors"]}
    )

    await change_source(
        corp, people={"carol": person("pw", display_name="Carol D.", email="cd@corp.example")}
    )
    again = await login(other_client, "carol", "pw")
    carol, held = await stored(sessionmaker, "carol")

    assert again.status_code == 200
    assert (carol.display_name, carol.email) == ("Carol D.", "cd@corp.example")
    # Her groups no longer give `developers`; `auditors` was an administrator's to give.
    assert held == {"auditors": "admin"}


async def test_a_name_one_of_our_own_has_is_checked_by_us_alone(
    client, make_user, add_source, sessionmaker
):
    await make_user("dana")
    await add_source("Corp HQ", {"dana": person("directory pw")})
    await add_source("corp-hq", {"dana": person("other directory pw")})

    first = await login(client, "dana", PASSWORD)  # the local dana is asked, and only her
    by_directory = await login(client, "dana", "directory pw")
    as_herself = await login(client, "dana@corp-hq", "directory pw")

    assert first.json()["user"]["username"] == "dana"
    assert by_directory.status_code == 401
    assert as_herself.status_code == 401  # nobody has the name yet: no source knows it so


async def test_a_directory_user_whose_name_is_taken_gets_name_at_source(
    client, make_user, add_source, sessionmaker
):
    corp = await add_source("Corp HQ", {"erin": person("pw", id="uid=erin")})
    await login(client, "erin", "pw")
    # A user of our own is given the name the directory's erin had, who is renamed so.
    erin, _ = await stored(sessionmaker, "erin")
    async with sessionmaker() as db:
        found = await db.get(User, erin.id)
        found.username = "erin.old"
        await db.commit()
    await make_user("erin")

    again = await login(client, "erin.old", "pw")
    renamed, _ = await stored(sessionmaker, "erin@corp-hq")

    assert again.status_code == 200
    assert (renamed.id, renamed.source_id) == (erin.id, corp.id)
    assert again.json()["user"]["username"] == "erin@corp-hq"


async def test_a_name_nobody_has_is_asked_of_each_source_in_order_and_the_first_who_knows_decides(
    client, add_source, change_source, sessionmaker
):
    first = await add_source("first", {"frank": person("first pw")})
    second = await add_source("second", {"frank": person("second pw"), "gina": person("g")})

    gina = await login(client, "gina", "g")  # the first does not know her: the second does
    wrong_at_first = await login(client, "frank", "second pw")
    await change_source(first, position=2)
    by_second = await login(client, "frank", "second pw")
    frank, _ = await stored(sessionmaker, "frank")

    assert gina.status_code == 200
    assert (wrong_at_first.status_code, error_code(wrong_at_first)) == (401, "unauthorized")
    assert by_second.status_code == 200
    assert frank.source_id == second.id


async def test_a_user_of_a_source_is_asked_of_their_own_source_alone(
    client, add_source, sessionmaker
):
    await add_source("first", {"hal": person("first pw", id="uid=hal,first")})
    await add_source("second", {"hal": person("second pw", id="uid=hal,second")})
    await login(client, "hal", "first pw")

    by_the_other = await login(client, "hal", "second pw")

    assert by_the_other.status_code == 401


async def test_a_user_of_a_source_signs_in_with_basic_and_makes_api_tokens(
    client, other_client, add_source
):
    await add_source("corp", {"ivy": person("ivy pw")})

    by_basic = await other_client.get(SESSION, headers=basic("ivy", "ivy pw"))
    await sign_in(client, "ivy", "ivy pw")
    made = await client.post("/api/v1/me/tokens", json={"name": "ci"})
    by_token = await other_client.get(SESSION, headers=bearer(made.json()["token"]))

    assert by_basic.json()["user"]["username"] == "ivy"
    assert made.status_code == 201
    assert by_token.json()["user"]["username"] == "ivy"


async def test_a_source_turned_off_signs_nobody_in_and_refuses_its_users(
    client, other_client, add_source, change_source
):
    corp = await add_source("corp", {"jo": person("jo pw")})
    await sign_in(client, "jo", "jo pw")
    token = (await client.post("/api/v1/me/tokens", json={"name": "ci"})).json()["token"]
    await add_source("off", {"kim": person("kim pw")}, enabled=False)

    await change_source(corp, enabled=False)
    session = (await client.get(SESSION)).json()
    by_token = await other_client.get(SESSION, headers=bearer(token))
    jo = await login(other_client, "jo", "jo pw")
    kim = await login(other_client, "kim", "kim pw")
    await change_source(corp, enabled=True)
    back = (await client.get(SESSION)).json()

    assert session["authenticated"] is False
    assert (by_token.status_code, jo.status_code, kim.status_code) == (401, 401, 401)
    assert back["user"]["username"] == "jo"


async def test_a_user_an_administrator_disabled_is_refused_whatever_the_directory_says(
    admin_client, other_client, add_source, sessionmaker
):
    await add_source("corp", {"lee": person("lee pw")})
    await login(other_client, "lee", "lee pw")
    lee, _ = await stored(sessionmaker, "lee")
    await admin_client.patch(f"/api/v1/users/{lee.id}", json={"status": "disabled"})

    again = await login(other_client, "lee", "lee pw")

    assert again.status_code == 401


async def test_a_source_that_does_not_answer_is_named_and_counts_no_failure(client, add_source):
    await add_source("corp", {"max": person("pw")}, down=True)

    answers = [await login(client, "max", "pw") for _ in range(6)]

    assert {(answer.status_code, error_code(answer)) for answer in answers} == {
        (503, "source_unavailable")
    }
    assert "corp" in answers[0].json()["error"]["message"]


async def test_failed_sign_ins_through_a_source_are_limited_as_ours_are(client, add_source):
    await add_source("corp", {"ned": person("pw")})

    answers = [await login(client, "ned", "wrong") for _ in range(6)]

    assert [answer.status_code for answer in answers] == [401] * 5 + [429]


async def test_the_password_of_a_user_of_a_source_is_the_sources(
    admin_client, other_client, add_source, sessionmaker
):
    await add_source("corp", {"oli": person("oli pw")})
    await sign_in(other_client, "oli", "oli pw")
    oli, _ = await stored(sessionmaker, "oli")

    by_admin = await admin_client.put(
        f"/api/v1/users/{oli.id}/password", json={"password": "a new long password"}
    )
    by_oli = await other_client.put(
        "/api/v1/me/password",
        json={"current_password": "oli pw", "new_password": "a new long password"},
    )

    assert (by_admin.status_code, error_code(by_admin)) == (409, "external_user")
    assert (by_oli.status_code, error_code(by_oli)) == (409, "external_user")


async def test_a_name_a_source_gives_that_is_nobodys_is_given_another(
    client, add_source, sessionmaker
):
    await add_source("corp", {"pat": person("pw", username="__token__", id="uid=pat")})

    signed_in = await login(client, "pat", "pw")

    assert signed_in.json()["user"]["username"] == "__token__@corp"
