"""V3's search and autocomplete of a hosted NuGet repository, as nuget.org answers them."""

import pytest

from tests.repositories.nuget.conftest import BASE, URL, push
from tests.repositories.nuget.packages import nupkg


@pytest.fixture
async def held(client, hosted, root):
    """Four ids: one with a prerelease after its stable version, one prerelease alone."""
    for package_id, version, description, tags in [
        ("MegooArti.Hello", "1.0.0", "Says hello.", "greeting"),
        ("MegooArti.Hello", "2.0.0-beta", "Says hello, louder.", "greeting"),
        ("MegooArti.Hello.Extras", "1.0.0", "More of it.", "extras"),
        ("Hello", "3.0.0", "The first hello.", "greeting"),
        ("Nightly.Tool", "0.1.0-alpha", "Only ever a prerelease.", "tool"),
    ]:
        answer = await push(
            client, root, nupkg(package_id, version, description=description, tags=tags)
        )
        assert answer.status_code == 201, answer.text


async def search(client, root, **arguments) -> dict:
    answer = await client.get(f"{URL}/v3/search", params=arguments, headers=root)
    assert answer.status_code == 200, answer.text
    return answer.json()


async def test_a_search_finds_ids_by_their_words_with_their_versions(client, root, held):
    found = await search(client, root, q="hello")

    assert found["totalHits"] == 3
    # The exact id first, then the ids that begin with what was typed.
    assert [package["id"] for package in found["data"]] == [
        "Hello",
        "MegooArti.Hello",
        "MegooArti.Hello.Extras",
    ]
    hello = found["data"][1]
    assert hello["version"] == "1.0.0"  # its prerelease is not asked for
    assert [version["version"] for version in hello["versions"]] == ["1.0.0"]
    assert hello["registration"] == f"{BASE}v3/registration/megooarti.hello/index.json"
    assert hello["description"] == "Says hello."
    assert hello["tags"] == ["greeting"]


async def test_prereleases_are_found_when_asked_for(client, root, held):
    found = await search(client, root, q="", prerelease="true")

    by_id = {package["id"]: package for package in found["data"]}
    assert found["totalHits"] == 4
    assert by_id["MegooArti.Hello"]["version"] == "2.0.0-beta"
    assert [one["version"] for one in by_id["MegooArti.Hello"]["versions"]] == [
        "1.0.0",
        "2.0.0-beta",
    ]
    assert "Nightly.Tool" in by_id
    without = await search(client, root, q="")
    assert "Nightly.Tool" not in {package["id"] for package in without["data"]}


async def test_a_search_by_id_and_a_search_by_tag(client, root, held):
    exact = await search(client, root, q="packageid:megooarti.hello")
    contains = await search(client, root, q="id:extras")
    tagged = await search(client, root, q="greeting")

    assert [package["id"] for package in exact["data"]] == ["MegooArti.Hello"]
    assert [package["id"] for package in contains["data"]] == ["MegooArti.Hello.Extras"]
    assert {package["id"] for package in tagged["data"]} == {"Hello", "MegooArti.Hello"}


async def test_a_search_comes_a_page_at_a_time(client, root, held):
    page = await search(client, root, q="hello", skip="1", take="1")

    assert page["totalHits"] == 3
    assert [package["id"] for package in page["data"]] == ["MegooArti.Hello"]


@pytest.mark.parametrize(
    "arguments", [{"take": "1001"}, {"skip": "2500", "take": "600"}, {"skip": "-1"}]
)
async def test_a_search_beyond_its_bounds_is_refused(client, hosted, root, arguments):
    answer = await client.get(f"{URL}/v3/search", params=arguments, headers=root)

    assert answer.status_code == 400


async def test_autocomplete_gives_ids_and_an_ids_versions(client, root, held):
    ids = await client.get(f"{URL}/v3/autocomplete", params={"q": "megooarti"}, headers=root)
    held_versions = await client.get(
        f"{URL}/v3/autocomplete",
        params={"id": "megooarti.hello", "prerelease": "true"},
        headers=root,
    )

    assert ids.json() == {"totalHits": 2, "data": ["MegooArti.Hello", "MegooArti.Hello.Extras"]}
    assert held_versions.json() == {"totalHits": 2, "data": ["1.0.0", "2.0.0-beta"]}


async def test_a_page_of_names_is_chosen_in_the_database_and_all_are_counted(
    db, hosted, held, context_for
):
    context = await context_for(hosted, None)

    names, total = await context.package_page(
        "", ["hello"], ranked_by="hello", stable_only=True, limit=2, offset=0
    )
    rest, _ = await context.package_page(
        "", ["hello"], ranked_by="hello", stable_only=True, limit=2, offset=2
    )
    nightly, count = await context.package_page("", [], stable_only=False, limit=1, offset=0)
    stable, stable_count = await context.package_page("", [], stable_only=True, limit=10, offset=0)

    assert (names, total) == (["Hello", "MegooArti.Hello"], 3)
    assert rest == ["MegooArti.Hello.Extras"]
    assert (len(nightly), count) == (1, 4)
    assert "Nightly.Tool" not in stable and stable_count == 3


async def test_the_versions_of_the_names_of_a_page_are_read_together(db, hosted, held, context_for):
    context = await context_for(hosted, None)

    got = await context.components_of("", ["MegooArti.Hello", "Hello"])

    assert {name: sorted(one.version for one in infos) for name, infos in got.items()} == {
        "MegooArti.Hello": ["1.0.0", "2.0.0-beta"],
        "Hello": ["3.0.0"],
    }
