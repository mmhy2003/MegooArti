"""A proxy of a V3 feed, as nuget.org is one: its documents passed on with the proxy's own
addresses, its packages kept and read as pushed ones are, its search passed on."""

import gzip
import json

import pytest

from megooarti.repositories.nuget.format import NuGetFormat
from tests.accounts import error_code
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg, nuspec

PROXY = "/repository/nuget-org"
BASE = "https://test/repository/nuget-org/"
REMOTE = "http://remote.test/nuget"
SEARCH = "http://search.test"
PACKAGE = nupkg("Newtonsoft.Json", "13.0.3", description="Json.NET is a JSON framework.")
FLAT = "nuget/v3-flatcontainer/newtonsoft.json"


def service_index(*, search: bool = True) -> bytes:
    """The remote's service index, as nuget.org's lays it out: search on another host."""
    resources = [
        {"@id": f"{REMOTE}/v3-flatcontainer/", "@type": "PackageBaseAddress/3.0.0"},
        {"@id": f"{REMOTE}/registration-gz-semver2/", "@type": "RegistrationsBaseUrl/3.6.0"},
        {"@id": f"{REMOTE}/registration-semver1/", "@type": "RegistrationsBaseUrl"},
    ]
    if search:
        resources += [
            {"@id": f"{SEARCH}/query", "@type": "SearchQueryService/3.5.0"},
            {"@id": f"{SEARCH}/autocomplete", "@type": "SearchAutocompleteService/3.5.0"},
        ]
    return json.dumps({"version": "3.0.0", "resources": resources}).encode()


def registration() -> dict:
    """nuget.org's registration of one id, with a page elsewhere and a dependency."""
    index = f"{REMOTE}/registration-gz-semver2/newtonsoft.json/index.json"
    return {
        "@id": index,
        "count": 2,
        "items": [
            {
                "@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/page/1.0.0/12.0.3.json",
                "count": 64,
                "lower": "1.0.0",
                "upper": "12.0.3",
            },
            {
                "@id": f"{index}#page/13.0.1/13.0.3",
                "count": 1,
                "lower": "13.0.3",
                "upper": "13.0.3",
                "items": [
                    {
                        "@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/13.0.3.json",
                        "packageContent": (
                            f"{REMOTE}/v3-flatcontainer/newtonsoft.json/13.0.3/"
                            "newtonsoft.json.13.0.3.nupkg"
                        ),
                        "catalogEntry": {
                            "id": "Newtonsoft.Json",
                            "version": "13.0.3",
                            "dependencyGroups": [
                                {
                                    "dependencies": [
                                        {
                                            "id": "Other",
                                            "range": "[1.0.0, )",
                                            "registration": (
                                                f"{REMOTE}/registration-semver1/other/index.json"
                                            ),
                                        }
                                    ]
                                }
                            ],
                        },
                    }
                ],
            },
        ],
    }


@pytest.fixture
async def nuget_org(client, root):
    """A proxy of the stand-in feed that asks about metadata every time it is asked."""
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-org",
            "format": "nuget",
            "type": "proxy",
            "proxy": {"remote_url": f"{REMOTE}/v3/index.json", "metadata_max_age_minutes": 0},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text
    return made.json()


@pytest.fixture
def remote(fake_remote, nuget_org):
    fake_remote.files["nuget/v3/index.json"] = service_index()
    fake_remote.files[f"{FLAT}/index.json"] = b'{"versions":["12.0.3","13.0.3"]}'
    fake_remote.files[f"{FLAT}/13.0.3/newtonsoft.json.13.0.3.nupkg"] = PACKAGE
    fake_remote.files[f"{FLAT}/13.0.3/newtonsoft.json.nuspec"] = nuspec(
        "Newtonsoft.Json", "13.0.3", description="Json.NET is a JSON framework."
    )
    page = "nuget/registration-gz-semver2/newtonsoft.json"
    fake_remote.files[f"{page}/index.json"] = gzip.compress(json.dumps(registration()).encode())
    fake_remote.encodings[f"{page}/index.json"] = "gzip"  # as nuget.org's are, asked or not
    fake_remote.files[f"{page}/page/1.0.0/12.0.3.json"] = json.dumps(
        {"@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/page/1.0.0/12.0.3.json"}
    ).encode()
    found = {
        "totalHits": 1,
        "data": [
            {
                "@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/index.json",
                "id": "Newtonsoft.Json",
                "version": "13.0.3",
                "registration": f"{REMOTE}/registration-semver1/newtonsoft.json/index.json",
            }
        ],
    }
    fake_remote.files["query"] = json.dumps(found).encode()
    fake_remote.files["autocomplete"] = b'{"totalHits":1,"data":["Newtonsoft.Json"]}'
    return fake_remote


async def test_a_proxy_has_a_service_index_of_its_own_and_takes_no_push(client, root, remote):
    answer = await client.get(f"{PROXY}/index.json", headers=root)

    resources = {item["@type"]: item["@id"] for item in answer.json()["resources"]}
    assert resources["PackageBaseAddress/3.0.0"] == f"{BASE}v3/package/"
    assert resources["RegistrationsBaseUrl/3.6.0"] == f"{BASE}v3/registration/"
    assert resources["SearchQueryService/3.5.0"] == f"{BASE}v3/search"
    assert "PackagePublish/2.0.0" not in resources
    pushed = await push(client, root, PACKAGE, repository="nuget-org")
    assert pushed.status_code == 405


async def test_a_proxy_searches_only_where_its_remote_does(client, root, remote):
    remote.files["nuget/v3/index.json"] = service_index(search=False)

    resources = (await client.get(f"{PROXY}/index.json", headers=root)).json()["resources"]

    assert not [item for item in resources if item["@type"].startswith("Search")]
    assert (await client.get(f"{PROXY}/v3/search", headers=root)).status_code == 404


async def test_a_service_index_that_cannot_be_used_is_said_to_be_so(client, root, remote):
    remote.files["nuget/v3/index.json"] = b'{"resources": []}'

    answer = await client.get(f"{PROXY}/index.json", headers=root)

    assert (answer.status_code, error_code(answer)) == (502, "remote_unavailable")
    assert "PackageBaseAddress" in answer.json()["error"]["message"]


async def test_a_package_is_kept_and_its_versions_are_asked_about_again(client, root, remote):
    folder = "v3/package/newtonsoft.json"
    for _ in range(2):
        listed = await client.get(f"{PROXY}/{folder}/index.json", headers=root)
        fetched = await client.get(
            f"{PROXY}/{folder}/13.0.3/newtonsoft.json.13.0.3.nupkg", headers=root
        )

    assert listed.json() == {"versions": ["12.0.3", "13.0.3"]}
    assert fetched.content == PACKAGE
    assert remote.paths().count(f"/{FLAT}/index.json") == 2  # metadata: its age is 0
    assert remote.paths().count(f"/{FLAT}/13.0.3/newtonsoft.json.13.0.3.nupkg") == 1


async def test_a_kept_package_is_read_as_a_pushed_one_is(client, root, remote):
    folder = "v3/package/newtonsoft.json/13.0.3"
    await client.get(f"{PROXY}/{folder}/newtonsoft.json.13.0.3.nupkg", headers=root)
    await client.get(f"{PROXY}/{folder}/newtonsoft.json.nuspec", headers=root)

    components = (await client.get("/api/v1/content/nuget-org/components", headers=root)).json()
    found = await client.get("/api/v1/search", params={"q": "framework"}, headers=root)

    # Its .nupkg and .nuspec are one version, spelled as the package spells its id.
    assert [(item["name"], item["version"]) for item in components["items"]] == [
        ("Newtonsoft.Json", "13.0.3")
    ]
    assert [item["name"] for item in found.json()["items"]] == ["Newtonsoft.Json"]


async def test_a_registration_is_passed_on_with_the_proxys_addresses(client, root, remote):
    answer = await client.get(f"{PROXY}/v3/registration/newtonsoft.json/index.json", headers=root)

    document = answer.json()
    assert answer.status_code == 200, answer.text
    assert document["@id"] == f"{BASE}v3/registration/newtonsoft.json/index.json"
    paged, inlined = document["items"]
    assert paged["@id"] == f"{BASE}v3/registration/newtonsoft.json/page/1.0.0/12.0.3.json"
    (item,) = inlined["items"]
    assert item["packageContent"] == (
        f"{BASE}v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg"
    )
    (dependency,) = item["catalogEntry"]["dependencyGroups"][0]["dependencies"]
    # A registration of another kind of the remote's is the proxy's one registration.
    assert dependency["registration"] == f"{BASE}v3/registration/other/index.json"
    page = await client.get(paged["@id"].removeprefix("https://test"), headers=root)
    assert page.json()["@id"] == paged["@id"]


async def test_what_the_remote_sent_is_kept_and_given_while_it_cannot_be_reached(
    client, root, remote
):
    registration_path = f"{PROXY}/v3/registration/newtonsoft.json/index.json"
    package_path = f"{PROXY}/v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg"
    await client.get(registration_path, headers=root)
    await client.get(package_path, headers=root)
    remote.down = True

    registration_answer = await client.get(registration_path, headers=root)
    package_answer = await client.get(package_path, headers=root)

    assert registration_answer.status_code == 200
    assert registration_answer.json()["@id"].startswith(BASE)
    assert package_answer.content == PACKAGE


async def test_a_search_is_passed_on_as_it_came_every_time_with_the_proxys_addresses(
    client, root, remote
):
    for _ in range(2):
        answer = await client.get(
            f"{PROXY}/v3/search",
            params={"q": "json", "prerelease": "true", "semVerLevel": "2.0.0"},
            headers=root,
        )

    (found,) = answer.json()["data"]
    assert found["registration"] == f"{BASE}v3/registration/newtonsoft.json/index.json"
    asked = [seen for seen in remote.requests if seen["path"] == "/query"]
    assert len(asked) == 2  # not kept
    assert asked[-1]["host"] == "search.test"
    assert asked[-1]["query"] == "q=json&prerelease=true&semVerLevel=2.0.0"
    completed = await client.get(f"{PROXY}/v3/autocomplete", params={"q": "newt"}, headers=root)
    assert completed.json() == {"totalHits": 1, "data": ["Newtonsoft.Json"]}


@pytest.mark.parametrize(
    ("path", "metadata"),
    [
        (".remote/index.json", True),
        ("v3/package/newtonsoft.json/index.json", True),
        ("v3/registration/newtonsoft.json/index.json", True),
        ("v3/registration/newtonsoft.json/page/1.0.0/12.0.3.json", True),
        ("v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg", False),
        ("v3/package/newtonsoft.json/13.0.3/newtonsoft.json.nuspec", False),
    ],
)
def test_an_ids_versions_and_its_registration_are_metadata_and_a_package_is_not(path, metadata):
    assert NuGetFormat().is_metadata(path) is metadata


async def test_a_proxys_settings_are_its_protocol_and_a_symbol_server(client, root):
    def made(name: str, format_config: dict):
        return client.post(
            "/api/v1/repositories",
            json={
                "name": name,
                "format": "nuget",
                "type": "proxy",
                "proxy": {"remote_url": "https://api.nuget.org/v3/index.json"},
                "format_config": format_config,
            },
            headers=root,
        )

    plain = await made("plain", {})
    symbols = await made(
        "symbols", {"protocol": "v3", "symbol_url": "https://symbols.nuget.org/download/symbols/"}
    )
    v2 = await made("v2", {"protocol": "v2"})
    wrong = await made("wrong", {"symbol_url": "ftp://symbols.test"})
    unknown = await made("unknown", {"suite": "stable"})

    assert plain.json()["format_config"] == {"protocol": "v3"}
    assert symbols.json()["format_config"] == {
        "protocol": "v3",
        "symbol_url": "https://symbols.nuget.org/download/symbols",
    }
    for refused, field in ((v2, "protocol"), (wrong, "symbol_url"), (unknown, "suite")):
        assert refused.status_code == 422
        assert refused.json()["error"]["details"][0]["field"] == f"format_config.{field}"
