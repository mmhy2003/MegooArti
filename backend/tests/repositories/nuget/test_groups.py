"""A group of NuGet repositories: one V3 feed of its members' (spec 7.1, 7.2) — an id's
versions together, its registration written by the group from its members' items, a
search merged in the members' order, a package from the first member that has it."""

import gzip
import json

import pytest

from megooarti.repositories.nuget import documents
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg

GROUP = "/repository/nuget-all"
BASE = "https://test/repository/nuget-all/"
REMOTE = "http://remote.test/nuget"
PUSHED = "Pushed here."
FETCHED = nupkg("MegooArti.Hello", "3.0.0", description="On the feed.")


def service_index(*, vulnerabilities: bool = False) -> bytes:
    resources = [
        {"@id": f"{REMOTE}/v3-flatcontainer/", "@type": "PackageBaseAddress/3.0.0"},
        {"@id": f"{REMOTE}/registration/", "@type": "RegistrationsBaseUrl/3.6.0"},
        {"@id": f"{REMOTE}/query", "@type": "SearchQueryService/3.5.0"},
        {"@id": f"{REMOTE}/autocomplete", "@type": "SearchAutocompleteService/3.5.0"},
    ]
    if vulnerabilities:
        resources.append(
            {"@id": f"{REMOTE}/v3/vulnerabilities/index.json", "@type": "VulnerabilityInfo/6.7.0"}
        )
    return json.dumps({"version": "3.0.0", "resources": resources}).encode()


def remote_item(package_id: str, version: str, description: str = "On the feed.") -> dict:
    """A version as the feed's registration lists it, at the feed's addresses."""
    lower = package_id.lower()
    return {
        "@id": f"{REMOTE}/registration/{lower}/{version}.json",
        "@type": "Package",
        "packageContent": f"{REMOTE}/v3-flatcontainer/{lower}/{version}/{lower}.{version}.nupkg",
        "registration": f"{REMOTE}/registration/{lower}/index.json",
        "catalogEntry": {
            "@id": f"{REMOTE}/catalog/{lower}.{version}.json",
            "id": package_id,
            "version": version,
            "description": description,
            "listed": True,
            "published": "2026-01-01T00:00:00+00:00",
        },
    }


def remote_registration(remote, package_id: str, items: list[dict]) -> None:
    """The feed's registration of an id, its versions inlined in one page, gzipped."""
    path = f"nuget/registration/{package_id.lower()}/index.json"
    index = f"{REMOTE}/registration/{package_id.lower()}/index.json"
    listed = [item["catalogEntry"]["version"] for item in items]
    page = {
        "@id": f"{index}#page/{listed[0]}/{listed[-1]}",
        "count": len(items),
        "lower": listed[0],
        "upper": listed[-1],
        "items": items,
    }
    document = {"@id": index, "count": 1, "items": [page]}
    remote.files[path] = gzip.compress(json.dumps(document).encode())
    remote.encodings[path] = "gzip"


@pytest.fixture
async def group(client, hosted, root, fake_remote):
    """`nuget-all`: a hosted repository with MegooArti.Hello 1.0.0 and 2.0.0, then a proxy
    of a feed with its 1.0.0 and 3.0.0 and with Newtonsoft.Json 13.0.3."""
    for version in ("1.0.0", "2.0.0"):
        package = nupkg("MegooArti.Hello", version, description=PUSHED)
        assert (await push(client, root, package)).status_code == 201
    for made in [
        {
            "name": "nuget-org",
            "format": "nuget",
            "type": "proxy",
            "proxy": {"remote_url": f"{REMOTE}/v3/index.json", "metadata_max_age_minutes": 0},
        },
        {
            "name": "nuget-all",
            "format": "nuget",
            "type": "group",
            "group": {"members": ["nuget-hosted", "nuget-org"]},
        },
    ]:
        answer = await client.post("/api/v1/repositories", json=made, headers=root)
        assert answer.status_code == 201, answer.text
    fake_remote.files["nuget/v3/index.json"] = service_index()
    flat = "nuget/v3-flatcontainer/megooarti.hello"
    fake_remote.files[f"{flat}/index.json"] = b'{"versions":["1.0.0","3.0.0"]}'
    fake_remote.files[f"{flat}/3.0.0/megooarti.hello.3.0.0.nupkg"] = FETCHED
    fake_remote.files[f"{flat}/1.0.0/megooarti.hello.1.0.0.nupkg"] = b"never asked for"
    remote_registration(
        fake_remote,
        "MegooArti.Hello",
        [remote_item("MegooArti.Hello", "1.0.0"), remote_item("MegooArti.Hello", "3.0.0")],
    )
    remote_registration(fake_remote, "Newtonsoft.Json", [remote_item("Newtonsoft.Json", "13.0.3")])
    return fake_remote


async def get(client, root, path: str, **arguments):
    return await client.get(f"{GROUP}/{path}", params=arguments, headers=root)


async def test_a_group_has_a_service_index_of_its_own_and_takes_no_push(client, root, group):
    answer = await get(client, root, "index.json")

    resources = {item["@type"]: item["@id"] for item in answer.json()["resources"]}
    assert resources["PackageBaseAddress/3.0.0"] == f"{BASE}v3/package/"
    assert resources["RegistrationsBaseUrl/3.6.0"] == f"{BASE}v3/registration/"
    assert resources["SearchQueryService/3.5.0"] == f"{BASE}v3/search"
    assert "PackagePublish/2.0.0" not in resources
    assert "VulnerabilityInfo/6.7.0" not in resources  # no member has NuGet Audit's data
    pushed = await push(client, root, nupkg("Brand.New", "1.0.0"), repository="nuget-all")
    assert pushed.status_code == 405


async def test_an_ids_versions_are_its_members_together(client, root, group):
    nested = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-outer",
            "format": "nuget",
            "type": "group",
            "group": {"members": ["nuget-all"]},
        },
        headers=root,
    )
    assert nested.status_code == 201, nested.text

    listed = await get(client, root, "v3/package/megooarti.hello/index.json")
    outer = await client.get(
        "/repository/nuget-outer/v3/package/megooarti.hello/index.json", headers=root
    )
    unknown = await get(client, root, "v3/package/nothing.here/index.json")

    assert listed.json() == {"versions": ["1.0.0", "2.0.0", "3.0.0"]}
    assert outer.json() == listed.json()
    assert unknown.status_code == 404


async def test_a_registration_is_the_groups_own_with_the_first_members_item_of_a_version(
    client, root, group
):
    answer = await get(client, root, "v3/registration/megooarti.hello/index.json")

    document = answer.json()
    assert answer.status_code == 200, answer.text
    assert document["@id"] == f"{BASE}v3/registration/megooarti.hello/index.json"
    (page,) = document["items"]
    assert (page["count"], page["lower"], page["upper"]) == (3, "1.0.0", "3.0.0")
    shown = {item["catalogEntry"]["version"]: item for item in page["items"]}
    assert list(shown) == ["1.0.0", "2.0.0", "3.0.0"]
    assert shown["1.0.0"]["catalogEntry"]["description"] == PUSHED  # the first member's
    assert shown["3.0.0"]["catalogEntry"]["description"] == "On the feed."
    assert shown["3.0.0"]["packageContent"] == (
        f"{BASE}v3/package/megooarti.hello/3.0.0/megooarti.hello.3.0.0.nupkg"
    )
    # Every address a client follows is the group's: none of a member's, none of the feed's.
    assert "/repository/nuget-hosted/" not in answer.text
    assert "/repository/nuget-org/" not in answer.text
    assert f"{REMOTE}/registration/" not in answer.text
    assert f"{REMOTE}/v3-flatcontainer/" not in answer.text


async def test_a_versions_leaf_is_written_from_its_item(client, root, group):
    leaf = await get(client, root, "v3/registration/megooarti.hello/3.0.0.json")
    unknown = await get(client, root, "v3/registration/megooarti.hello/9.0.0.json")

    assert leaf.status_code == 200, leaf.text
    assert leaf.json()["@id"] == f"{BASE}v3/registration/megooarti.hello/3.0.0.json"
    assert leaf.json()["packageContent"] == (
        f"{BASE}v3/package/megooarti.hello/3.0.0/megooarti.hello.3.0.0.nupkg"
    )
    assert leaf.json()["registration"] == f"{BASE}v3/registration/megooarti.hello/index.json"
    assert unknown.status_code == 404


async def test_a_registration_of_more_than_128_versions_is_paged_by_the_group(client, root, group):
    many = [remote_item("Many.Versions", f"1.{minor}.0") for minor in range(129)]
    remote_registration(group, "Many.Versions", many)

    index = (await get(client, root, "v3/registration/many.versions/index.json")).json()
    second = await get(client, root, "v3/registration/many.versions/page/1.64.0/1.127.0.json")
    unknown = await get(client, root, "v3/registration/many.versions/page/1.0.0/1.62.0.json")

    assert [(page["count"], page["lower"], page["upper"]) for page in index["items"]] == [
        (64, "1.0.0", "1.63.0"),
        (64, "1.64.0", "1.127.0"),
        (1, "1.128.0", "1.128.0"),
    ]
    assert all("items" not in page for page in index["items"])
    assert second.json()["@id"] == f"{BASE}v3/registration/many.versions/page/1.64.0/1.127.0.json"
    assert [item["catalogEntry"]["version"] for item in second.json()["items"]] == [
        f"1.{minor}.0" for minor in range(64, 128)
    ]
    assert unknown.status_code == 404


async def test_a_package_comes_from_the_first_member_that_has_it(client, root, group):
    folder = "v3/package/megooarti.hello"
    pushed = await get(client, root, f"{folder}/1.0.0/megooarti.hello.1.0.0.nupkg")
    fetched = await get(client, root, f"{folder}/3.0.0/megooarti.hello.3.0.0.nupkg")

    assert pushed.content == nupkg("MegooArti.Hello", "1.0.0", description=PUSHED)
    assert fetched.content == FETCHED
    assert "/nuget/v3-flatcontainer/megooarti.hello/1.0.0/" not in str(group.paths())


async def test_a_member_that_cannot_be_asked_is_passed_over(client, root, group):
    group.down = True

    listed = await get(client, root, "v3/package/megooarti.hello/index.json")
    registration = await get(client, root, "v3/registration/megooarti.hello/index.json")

    assert listed.json() == {"versions": ["1.0.0", "2.0.0"]}
    (page,) = registration.json()["items"]
    assert [item["catalogEntry"]["version"] for item in page["items"]] == ["1.0.0", "2.0.0"]


async def test_a_search_is_merged_in_the_members_order(client, root, group):
    found = [
        {"id": "MegooArti.Hello", "version": "3.0.0", "description": "On the feed."},
        {
            "id": "Newtonsoft.Json",
            "version": "13.0.3",
            "registration": f"{REMOTE}/registration/newtonsoft.json/index.json",
        },
    ]
    group.files["nuget/query"] = json.dumps({"totalHits": 2, "data": found}).encode()

    everything = (await get(client, root, "v3/search", q="")).json()
    second = (await get(client, root, "v3/search", q="", skip="1", take="1")).json()

    assert [item["id"] for item in everything["data"]] == ["MegooArti.Hello", "Newtonsoft.Json"]
    assert everything["data"][0]["description"] == PUSHED  # the first member's
    assert everything["data"][1]["registration"] == (
        f"{BASE}v3/registration/newtonsoft.json/index.json"
    )
    assert everything["totalHits"] == 2  # one, and two, less the one both have
    assert [item["id"] for item in second["data"]] == ["Newtonsoft.Json"]
    asked = [seen["query"] for seen in group.requests if seen["path"] == "/nuget/query"]
    # Each member is asked for the results up to the end of the page.
    assert "skip=0" in asked[-1] and "take=2" in asked[-1]


async def test_autocomplete_is_merged_in_the_members_order(client, root, group):
    group.files["nuget/autocomplete"] = b'{"totalHits":2,"data":["megooarti.hello","Other"]}'
    ids = (await get(client, root, "v3/autocomplete", q="o")).json()
    group.files["nuget/autocomplete"] = b'{"totalHits":3,"data":["1.0.0","3.0.0","4.0.0-beta"]}'
    shown = (await get(client, root, "v3/autocomplete", id="MegooArti.Hello")).json()

    assert ids == {"totalHits": 2, "data": ["MegooArti.Hello", "Other"]}
    assert shown == {"totalHits": 3, "data": ["1.0.0", "2.0.0", "3.0.0"]}


async def test_nuget_audits_data_comes_from_the_first_member_that_has_it(client, root, group):
    group.files["nuget/v3/index.json"] = service_index(vulnerabilities=True)
    listed = [{"@name": "base", "@id": f"{REMOTE}/v3-vulnerabilities/base.json"}]
    audit = {"system.text.json": [{"severity": 2, "url": "u", "versions": "[8.0.0, 8.0.4]"}]}
    for path, document in [
        ("nuget/v3/vulnerabilities/index.json", listed),
        ("nuget/v3-vulnerabilities/base.json", audit),
    ]:
        group.files[path] = gzip.compress(json.dumps(document).encode())
        group.encodings[path] = "gzip"

    resources = (await get(client, root, "index.json")).json()["resources"]
    index = await get(client, root, "v3/vulnerabilities/index.json")
    fetched = await get(client, root, "v3/vulnerabilities/base.json")

    offered = {item["@type"]: item["@id"] for item in resources}
    assert offered["VulnerabilityInfo/6.7.0"] == f"{BASE}v3/vulnerabilities/index.json"
    assert [(item["@name"], item["@id"]) for item in index.json()] == [
        ("base", f"{BASE}v3/vulnerabilities/base.json")
    ]
    assert fetched.json() == audit


async def test_a_group_without_audit_data_has_no_index_of_it(client, root, group):
    answer = await get(client, root, "v3/vulnerabilities/index.json")

    assert answer.status_code == 404


def test_a_groups_items_are_the_first_members_for_a_version_the_oldest_first():
    first = [{"catalogEntry": {"version": "2.0.0", "from": "first"}}]
    second = [
        {"catalogEntry": {"version": "2.0"}},
        {"catalogEntry": {"version": "1.0.0-Beta"}},
        {"catalogEntry": {"version": "not one"}},
        {"catalogEntry": {}},
    ]

    merged = documents.merged_items([first, second])

    assert [documents.version_of(item) for item in merged] == ["1.0.0-beta", "2.0.0"]
    assert merged[1]["catalogEntry"]["from"] == "first"


@pytest.mark.parametrize(
    ("path", "remote_path"),
    [("v3/search", "/nuget/query"), ("v3/autocomplete", "/nuget/autocomplete")],
)
async def test_a_page_far_down_is_asked_of_each_member_a_thousand_at_a_time(
    client, root, group, path, remote_path
):
    answer = await get(client, root, path, q="", skip="2990", take="10")

    assert answer.status_code == 200, answer.text
    asked = [seen["query"] for seen in group.requests if seen["path"] == remote_path]
    # The feed takes at most 1,000 at a time, as nuget.org does; it had fewer.
    assert asked == ["q=&skip=0&take=1000"]
