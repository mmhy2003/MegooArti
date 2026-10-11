"""Searching for components across repositories."""

import hashlib

import pytest

from megooarti.repositories import service
from megooarti.repositories.search import pattern
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.docker.conftest import push_image
from tests.repositories.npm.conftest import publish
from tests.repositories.pypi.conftest import upload

SEARCH = "/api/v1/search"
JAR = b"the bytes of the jar"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str, **settings):
    made = await service.create_repository(
        db,
        name=name,
        format=format,
        type=settings.pop("type", "hosted"),
        online=True,
        blob_store="default",
        **settings,
    )
    await db.commit()
    return made


@pytest.fixture
async def stocked(client, root, db, files) -> None:
    """Something of every format, in repositories named for it."""
    for name in ("maven", "npm", "pypi", "docker"):
        await create(db, name, name)
    for path, data in (
        ("com/acme/commons-lang/3.0/commons-lang-3.0.jar", JAR),
        ("com/acme/commons-lang/3.1/commons-lang-3.1.jar", b"3.1"),
        ("org/other/commons-io/1.0/commons-io-1.0.jar", b"io"),
    ):
        assert (
            await client.put(f"/repository/maven/{path}", content=data, headers=root)
        ).is_success
    await publish(client, root, "@acme/saw", "1.0.0", description="Cuts wood", keywords=["blade"])
    await publish(client, root, "commons", "2.0.0", description="100% shared_code")
    await upload(client, root, "greeter-1.0-py3-none-any.whl", summary="Says hello to commons")
    await push_image(client, root, "acme/saw", "1.0", "one", repository="docker")
    await client.put("/repository/files/docs/Commons-Guide.md", content=b"guide", headers=root)


async def find(client, headers, **params) -> list[str]:
    response = await client.get(SEARCH, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [
        f"{item['repository']}:{item['namespace']}:{item['name']}:{item['version']}"
        for item in response.json()["items"]
    ]


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("a*b", "a%b"),
        ("100%", r"100\%"),
        ("a_b", r"a\_b"),
        ("back\\slash", "back\\\\slash"),
        ("*", "%"),
        ("plain", "plain"),
    ],
)
def test_what_is_typed_becomes_a_pattern_in_which_only_the_star_means_anything(typed, expected):
    assert pattern(typed) == expected


async def test_a_word_finds_what_contains_it_in_every_format(client, root, stocked):
    found = await find(client, root, q="commons")

    assert found == [
        "files:docs:Commons-Guide.md:",
        "npm::commons:2.0.0",
        "maven:org.other:commons-io:1.0",
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
        "pypi::greeter:1.0",  # by its summary
    ]


async def test_results_say_where_and_what_each_component_is(client, root, stocked):
    response = await client.get(SEARCH, params={"q": "saw", "format": "npm"}, headers=root)

    (item,) = response.json()["items"]
    assert (item["repository"], item["format"]) == ("npm", "npm")
    assert (item["namespace"], item["name"], item["version"]) == ("acme", "saw", "1.0.0")
    assert item["id"] and item["created"] and item["modified"]
    opened = await client.get(f"/api/v1/content/npm/components/{item['id']}", headers=root)
    assert opened.status_code == 200


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("COMMONS lang", ["maven:com.acme:commons-lang:3.1", "maven:com.acme:commons-lang:3.0"]),
        ("lang commons 3.1", ["maven:com.acme:commons-lang:3.1"]),
        ("com.acme:commons-lang:3.0", ["maven:com.acme:commons-lang:3.0"]),
        ("@acme/saw", ["npm:acme:saw:1.0.0"]),
        ("acme/saw:1.0", ["docker::acme/saw:1.0"]),
        ("blade", ["npm:acme:saw:1.0.0"]),
        ("cuts wood", ["npm:acme:saw:1.0.0"]),
        ("io", ["maven:org.other:commons-io:1.0"]),  # shorter than three characters is fine
        ("comm*lang", ["maven:com.acme:commons-lang:3.1", "maven:com.acme:commons-lang:3.0"]),
        ("lang*zzz", []),
        ("100%", ["npm::commons:2.0.0"]),
        ("10%0", []),  # a percent sign is itself
        ("shared_code", ["npm::commons:2.0.0"]),
        ("shared*code", ["npm::commons:2.0.0"]),
        ("sharedXcode", []),
        ("shared-code", []),  # an underscore is itself too
        ("nothing-like-this", []),
    ],
)
async def test_how_words_match(client, root, stocked, q, expected):
    assert await find(client, root, q=q) == expected


async def test_fields_match_a_whole_value(client, root, stocked):
    assert await find(client, root, name="commons") == ["npm::commons:2.0.0"]
    assert await find(client, root, name="commons*") == [
        "files:docs:Commons-Guide.md:",  # whatever the case
        "npm::commons:2.0.0",
        "maven:org.other:commons-io:1.0",
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
    ]
    assert await find(client, root, name="COMMONS-IO") == ["maven:org.other:commons-io:1.0"]
    assert await find(client, root, namespace="com.acme") == [
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
    ]
    assert await find(client, root, namespace="*acme") == [
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
        "npm:acme:saw:1.0.0",
    ]
    assert await find(client, root, version="3.*", name="commons-lang") == [
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
    ]
    assert await find(client, root, version="3") == []


async def test_where_to_look_is_narrowed_by_format_and_repository(client, root, stocked, db):
    await create(db, "more-maven", "maven")
    await client.put(
        "/repository/more-maven/com/acme/saw/1.0/saw-1.0.jar", content=b"saw", headers=root
    )

    assert await find(client, root, q="saw", format="maven") == ["more-maven:com.acme:saw:1.0"]
    assert await find(client, root, q="saw", repository="docker") == ["docker::acme/saw:1.0"]
    assert await find(client, root, q="saw", repository="npm", format="maven") == []
    assert await find(client, root, q="saw", repository="nothing") == []
    assert len(await find(client, root, q="saw")) == 3


async def test_a_checksum_finds_the_component_of_the_file(client, root, stocked):
    digests = {
        name: hashlib.new(name, JAR).hexdigest() for name in ("md5", "sha1", "sha256", "sha512")
    }

    for field, value in digests.items():
        assert await find(client, root, **{field: value}) == ["maven:com.acme:commons-lang:3.0"]
    assert await find(client, root, sha1=digests["sha1"], q="io") == []
    assert await find(client, root, sha1="0" * 40) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("sha1", "abc"), ("sha256", "G" * 64), ("md5", "a" * 33), ("sha512", "0" * 127 + "!")],
)
async def test_a_checksum_must_be_one(client, root, stocked, field, value):
    response = await client.get(SEARCH, params={field: value}, headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == field


async def test_with_nothing_to_look_for_everything_is_listed_a_page_at_a_time(
    client, root, stocked
):
    everything = await client.get(SEARCH, headers=root)
    page = await client.get(SEARCH, params={"limit": 2, "offset": 1}, headers=root)

    assert everything.json()["total"] == 8
    names = [item["name"] for item in everything.json()["items"]]
    assert names == sorted(names)  # in the order of their names
    assert [item["name"] for item in page.json()["items"]] == names[1:3]
    assert (page.json()["total"], page.json()["limit"], page.json()["offset"]) == (8, 2, 1)


async def test_what_a_format_keeps_for_itself_is_not_found(client, root, stocked):
    found = await find(client, root, q="sha256")
    images = await find(client, root, format="docker")

    assert found == []  # a manifest's component has its digest for a version
    assert images == ["docker::acme/saw:1.0"]


async def test_nothing_is_found_where_the_caller_may_not_browse(
    client, root, stocked, make_user, db
):
    may = ["repository:npm:npm:browse", "repository:maven:maven:read"]
    await roles.create_role(db, "npm-browsers", "", may, [])
    await db.commit()
    await make_user("reader", roles=["npm-browsers"])
    reader = basic("reader", PASSWORD)

    found = await find(client, reader, q="commons")
    elsewhere = await find(client, reader, q="commons", repository="maven")
    by_checksum = await find(client, reader, sha1=hashlib.sha1(JAR).hexdigest())
    everything = await client.get(SEARCH, headers=reader)
    nobody = await client.get(SEARCH, params={"q": "commons"})

    assert found == ["npm::commons:2.0.0"]
    assert elsewhere == by_checksum == []
    assert everything.json()["total"] == 2
    assert (nobody.status_code, error_code(nobody)) == (401, "unauthorized")


async def test_anyone_finds_what_the_anonymous_user_may_browse(client, root, stocked, db):
    await roles.create_role(db, "public", "", ["repository:npm:npm:browse"], [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    assert await find(client, {}, q="commons") == ["npm::commons:2.0.0"]


async def test_a_group_and_what_is_behind_it_is_found_once(client, root, stocked, db):
    await create(db, "all", "maven", type="group", group={"members": ["maven"]})

    assert await find(client, root, name="commons-io") == ["maven:org.other:commons-io:1.0"]
    assert await find(client, root, name="commons-io", repository="all") == []


async def test_more_words_than_make_sense_are_not_all_looked_at(client, root, stocked):
    many = " ".join(["commons"] * 10 + ["never-matches"])

    assert len(await find(client, root, q=many)) == 6


async def test_what_is_asked_for_has_a_length(client, root, stocked):
    response = await client.get(SEARCH, params={"q": "x" * 1025}, headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_checksum_is_taken_as_tools_print_it(client, root, stocked):
    sha256 = hashlib.sha256(JAR).hexdigest()
    found = ["maven:com.acme:commons-lang:3.0"]

    assert await find(client, root, sha256=sha256.upper()) == found  # as PowerShell prints it
    assert await find(client, root, sha256=f"  {sha256}\n") == found
    assert await find(client, root, sha256=f"sha256:{sha256}") == found  # as Docker writes it
    assert await find(client, root, sha1=f"SHA1:{hashlib.sha1(JAR).hexdigest()}") == found


@pytest.mark.parametrize(
    ("field", "length"),
    [
        ("q", 257),
        ("namespace", 257),
        ("name", 257),
        ("version", 256),
        ("repository", 65),
        ("format", 33),
    ],
)
async def test_nothing_longer_than_a_value_can_be_is_looked_for(
    client, root, stocked, field, length
):
    # A long pattern of stars and letters has no trigram to look up: it would read every row.
    too_long = await client.get(SEARCH, params={field: ("*a" * 200)[:length]}, headers=root)
    longest = await client.get(SEARCH, params={field: "a" * (length - 1)}, headers=root)

    assert (too_long.status_code, error_code(too_long)) == (422, "validation_error")
    assert longest.status_code == 200


async def test_pattern_characters_in_a_stored_name_and_in_a_field(client, root, files):
    for name in ("100%25.txt", "a_b.txt", "axb.txt", "plain.txt"):  # %25 is a percent sign
        await client.put(f"/repository/files/odd/{name}", content=b"x", headers=root)

    assert await find(client, root, name="100%*") == ["files:odd:100%.txt:"]
    assert await find(client, root, name="a_b.txt") == ["files:odd:a_b.txt:"]  # not axb.txt
    assert await find(client, root, q="a_b") == ["files:odd:a_b.txt:"]
    assert await find(client, root, name="%") == []
    assert await find(client, root, name="_______") == []


async def test_a_backslash_that_is_stored_is_found_as_itself(client, root, db):
    await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0", description="path C:\\Temp\\x and 50%_off")

    assert await find(client, root, q="c:\\temp") == ["npm::tool:1.0.0"]
    assert await find(client, root, q="c:*x") == ["npm::tool:1.0.0"]
    assert await find(client, root, q="50%_off") == ["npm::tool:1.0.0"]
    assert await find(client, root, q="c:\\\\temp") == []


async def test_a_page_far_into_the_list_is_the_same_rows(client, root, stocked):
    everything = await client.get(SEARCH, params={"limit": 200}, headers=root)
    names = [item["id"] for item in everything.json()["items"]]

    for offset in range(len(names)):
        page = await client.get(SEARCH, params={"limit": 3, "offset": offset}, headers=root)
        assert [item["id"] for item in page.json()["items"]] == names[offset : offset + 3]
        assert all(item["modified"] for item in page.json()["items"])
