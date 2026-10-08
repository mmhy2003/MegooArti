import pytest

from tests.accounts import error_code
from tests.repositories.npm.conftest import URL, publish

SEARCH = f"{URL}/-/v1/search"


@pytest.fixture
async def packages(client, registry, root) -> None:
    await publish(client, root, "left-pad", "1.0.0", description="Pads on the left")
    await publish(client, root, "left-pad", "1.3.0", description="Pads on the left, better")
    await publish(client, root, "right-pad", "0.1.0")
    await publish(client, root, "@acme/widget", "2.0.0", description="A widget")
    await publish(client, root, "unrelated", "1.0.0")


async def names(client, root, **query) -> list[str]:
    response = await client.get(SEARCH, params=query, headers=root)
    assert response.status_code == 200, response.text
    return [entry["package"]["name"] for entry in response.json()["objects"]]


async def test_search_finds_packages_by_name(client, packages, root):
    response = await client.get(SEARCH, params={"text": "pad"}, headers=root)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert [entry["package"]["name"] for entry in body["objects"]] == ["left-pad", "right-pad"]
    assert body["total"] == 2
    first = body["objects"][0]["package"]
    assert (first["version"], first["description"]) == ("1.3.0", "Pads on the left, better")
    assert body["objects"][1]["package"]["description"] == ""


async def test_search_matches_the_scope_and_ignores_case(client, packages, root):
    assert await names(client, root, text="ACME") == ["@acme/widget"]
    assert await names(client, root, text="Widget") == ["@acme/widget"]


async def test_an_empty_search_lists_everything_a_page_at_a_time(client, packages, root):
    everything = await names(client, root)
    first_two = await names(client, root, size=2)
    the_rest = await names(client, root, size=10, **{"from": 2})

    assert everything == ["left-pad", "right-pad", "unrelated", "@acme/widget"]
    assert first_two + the_rest == everything


async def test_search_characters_are_taken_literally(client, packages, root):
    assert await names(client, root, text="%") == []
    assert await names(client, root, text="_") == []
    assert await names(client, root, text="left-pa_") == []


async def test_odd_paging_falls_back_to_the_defaults(client, packages, root):
    assert len(await names(client, root, size="many", **{"from": "-3"})) == 4
    assert len(await names(client, root, size=100000)) == 4


async def test_search_finds_nothing_in_an_empty_repository(client, registry, root):
    response = await client.get(SEARCH, params={"text": "pad"}, headers=root)

    assert (response.json()["objects"], response.json()["total"]) == ([], 0)


async def test_search_is_read_only_and_needs_read(client, packages, root):
    written = await client.put(SEARCH, json={}, headers=root)
    anonymous = await client.get(SEARCH)

    assert (written.status_code, error_code(written)) == (405, "method_not_allowed")
    assert anonymous.status_code == 401


async def test_absurd_paging_numbers_fall_back_too(client, packages, root):
    assert len(await names(client, root, size="9" * 5000, **{"from": "9" * 5000})) == 4
