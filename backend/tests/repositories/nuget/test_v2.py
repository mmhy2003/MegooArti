"""NuGet's V2 protocol of a hosted repository: OData's Atom feeds, written from what was
pushed, answering the queries the clients of D7 send (see `test_odata.py`)."""

import base64
import hashlib
from xml.etree import ElementTree

import pytest

from tests.accounts import error_code
from tests.repositories.nuget.conftest import URL, push
from tests.repositories.nuget.packages import nupkg

BASE = "https://test/repository/nuget-hosted/"
ATOM = "{http://www.w3.org/2005/Atom}"
D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
M = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"


def entries(answer) -> list[dict[str, str]]:
    """Each entry's properties, and its content's address as `src`."""
    assert answer.status_code == 200, answer.text
    root = ElementTree.fromstring(answer.content)
    found = root.findall(f"{ATOM}entry") if root.tag == f"{ATOM}feed" else [root]
    listed = []
    for entry in found:
        properties = {
            child.tag.removeprefix(D): child.text or "" for child in entry.find(f"{M}properties")
        }
        properties["src"] = entry.find(f"{ATOM}content").get("src")
        listed.append(properties)
    return listed


def versions_of(answer) -> list[tuple[str, str]]:
    return [(one["Id"], one["NormalizedVersion"]) for one in entries(answer)]


def next_link(answer) -> str | None:
    root = ElementTree.fromstring(answer.content)
    links = [link.get("href") for link in root.findall(f"{ATOM}link") if link.get("rel") == "next"]
    return links[0] if links else None


async def get(client, root, path: str, **arguments):
    return await client.get(f"{URL}/{path}", params=arguments, headers=root)


@pytest.fixture
async def held(client, hosted, root):
    """MegooArti.Hello 1.0 (as its package writes it), 1.5.0 and 2.0.0-beta, and
    Other.Thing 3.0.0, which is tagged otherwise."""
    for package_id, version, description, tags in [
        ("MegooArti.Hello", "1.0", "Says hello.", "hello greeting"),
        ("MegooArti.Hello", "2.0.0-beta", "Says hello, louder.", "hello greeting"),
        ("MegooArti.Hello", "1.5.0", "Says hello again.", "hello greeting"),
        ("Other.Thing", "3.0.0", "Something else.", "other"),
    ]:
        package = nupkg(package_id, version, description=description, tags=tags)
        answer = await push(client, root, package)
        assert answer.status_code == 201, answer.text


async def test_the_root_names_its_one_collection_and_metadata_its_functions(client, root, held):
    service = await get(client, root, "")
    metadata = await get(client, root, "$metadata")

    assert service.headers["content-type"].startswith("application/xml")
    assert b'<collection href="Packages">' in service.content
    assert f'xml:base="{BASE}"'.encode() in service.content
    assert b'FunctionImport Name="FindPackagesById"' in metadata.content
    assert b'FunctionImport Name="Search"' in metadata.content
    assert b'Name="IsAbsoluteLatestVersion"' in metadata.content


async def test_find_packages_by_id_lists_every_version_the_oldest_first(client, root, held):
    answer = await get(client, root, "FindPackagesById()", id="'megooarti.hello'")

    found = entries(answer)
    assert answer.headers["content-type"].startswith("application/atom+xml")
    assert [one["Id"] for one in found] == ["MegooArti.Hello"] * 3
    assert [one["NormalizedVersion"] for one in found] == ["1.0.0", "1.5.0", "2.0.0-beta"]
    # As its package wrote it.
    assert [one["Version"] for one in found] == ["1.0", "1.5.0", "2.0.0-beta"]
    assert [one["IsLatestVersion"] for one in found] == ["false", "true", "false"]
    assert [one["IsAbsoluteLatestVersion"] for one in found] == ["false", "false", "true"]
    assert [one["IsPrerelease"] for one in found] == ["false", "false", "true"]
    assert found[0]["src"] == f"{BASE}package/MegooArti.Hello/1.0.0"


async def test_an_entry_has_its_packages_hash_and_size(client, hosted, root):
    package = nupkg("MegooArti.Hello", "1.0.0")
    await push(client, root, package)

    (entry,) = entries(await get(client, root, "Packages(Id='megooarti.hello',Version='1.0')"))
    missing = await get(client, root, "Packages(Id='megooarti.hello',Version='9.0.0')")

    assert entry["PackageHash"] == base64.b64encode(hashlib.sha512(package).digest()).decode()
    assert (entry["PackageHashAlgorithm"], entry["PackageSize"]) == ("SHA512", str(len(package)))
    assert entry["DownloadCount"] == "0"
    assert missing.status_code == 404


async def test_dependencies_are_written_as_v2_writes_them(client, hosted, root):
    groups = (
        '<group targetFramework="net8.0"><dependency id="Other.Thing" version="3.0.0"/></group>'
        '<group targetFramework="netstandard2.0"/>'
    )
    await push(client, root, nupkg(dependencies=groups))

    (entry,) = entries(await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'"))

    assert entry["Dependencies"] == "Other.Thing:[3.0.0, ):net8.0|::netstandard2.0"


async def test_choco_installs_the_newest_stable_version_of_an_id(client, root, held):
    answer = await get(
        client,
        root,
        "Packages()",
        **{"$filter": "(tolower(Id) eq 'megooarti.hello') and IsLatestVersion"},
    )

    assert versions_of(answer) == [("MegooArti.Hello", "1.5.0")]


async def test_a_search_finds_ids_by_their_words_and_prereleases_when_asked(client, root, held):
    choco = await get(
        client,
        root,
        "Search()",
        **{
            "$filter": "IsLatestVersion",
            "$orderby": "Id,Version desc",
            "searchTerm": "'hello'",
            "targetFramework": "''",
            "includePrerelease": "false",
        },
    )
    nuget = await get(
        client,
        root,
        "Search()",
        **{"$orderby": "Id", "searchTerm": "''", "includePrerelease": "true", "$top": "30"},
    )

    assert versions_of(choco) == [("MegooArti.Hello", "1.5.0")]
    assert versions_of(nuget) == [
        ("MegooArti.Hello", "1.0.0"),
        ("MegooArti.Hello", "1.5.0"),
        ("MegooArti.Hello", "2.0.0-beta"),
        ("Other.Thing", "3.0.0"),
    ]


async def test_powershells_ranges_wildcards_and_tags_are_answered(client, root, held):
    ranged = await get(
        client,
        root,
        "FindPackagesById()",
        **{
            "$filter": (
                "NormalizedVersion ge '1.0.0' and NormalizedVersion le '2.0.0' and "
                "IsPrerelease eq false and Id eq 'MegooArti.Hello'"
            ),
            "$orderby": "NormalizedVersion desc",
            "$inlinecount": "allpages",
            "id": "'MegooArti.Hello'",
        },
    )
    wildcard = await get(
        client, root, "Search()", **{"$filter": "IsLatestVersion and startswith(Id, 'megooarti')"}
    )
    tagged = await get(
        client,
        root,
        "Search()",
        **{"$filter": "IsLatestVersion and substringof('other', Tags) eq true", "$top": "6000"},
    )

    assert versions_of(ranged) == [("MegooArti.Hello", "1.5.0"), ("MegooArti.Hello", "1.0.0")]
    assert b"<m:count>2</m:count>" in ranged.content
    assert versions_of(wildcard) == [("MegooArti.Hello", "1.5.0")]
    assert versions_of(tagged) == [("Other.Thing", "3.0.0")]


async def test_a_page_is_at_most_100_versions_and_leads_to_the_next(client, hosted, root):
    for minor in range(101):
        await push(client, root, nupkg("MegooArti.Hello", f"1.{minor}.0"))

    first = await get(
        client, root, "FindPackagesById()", id="'MegooArti.Hello'", **{"$top": "6000"}
    )
    following = await client.get(next_link(first).removeprefix("https://test"), headers=root)
    counted = await get(client, root, "FindPackagesById()/$count", id="'MegooArti.Hello'")

    assert len(entries(first)) == 100
    assert next_link(first) == (
        f"{BASE}FindPackagesById()?id='MegooArti.Hello'&$top=6000&$skip=100"
    )
    assert versions_of(following) == [("MegooArti.Hello", "1.100.0")]
    assert next_link(following) is None
    assert (counted.text, counted.headers["content-type"]) == ("101", "text/plain")


async def test_a_package_is_downloaded_at_v2s_address(client, hosted, root):
    package = nupkg("MegooArti.Hello", "1.0.0")
    await push(client, root, package)

    fetched = await get(client, root, "package/megooarti.hello/1.0")
    missing = await get(client, root, "package/MegooArti.Hello/2.0.0")

    assert fetched.content == package
    assert missing.status_code == 404


async def test_a_v2_client_pushes_to_the_repository_and_deletes_under_it(client, hosted, root):
    pushed = await client.put(
        f"{URL}/", files={"package": ("x.nupkg", nupkg(), "application/octet-stream")}, headers=root
    )
    deleted = await client.delete(f"{URL}/MegooArti.Hello/1.0.0", headers=root)
    again = await client.delete(f"{URL}/MegooArti.Hello/1.0.0", headers=root)

    assert pushed.status_code == 201, pushed.text
    assert deleted.status_code == 204
    assert again.status_code == 404


async def test_a_slash_too_many_before_a_v2_path_is_passed_over(client, root, held):
    # PSResourceGet adds a slash to an address that ends in one.
    found = await client.get(
        f"{URL}//FindPackagesById()", params={"id": "'Other.Thing'"}, headers=root
    )
    fetched = await client.get(f"{URL}//package/Other.Thing/3.0.0", headers=root)

    assert versions_of(found) == [("Other.Thing", "3.0.0")]
    assert fetched.status_code == 200


async def test_a_query_no_client_sends_is_refused_with_what_is_not_answered(client, root, held):
    answer = await get(client, root, "Packages()", **{"$filter": "Title eq 'x'"})

    assert (answer.status_code, error_code(answer)) == (400, "unsupported_query")
    assert "Title eq 'x'" in answer.json()["error"]["message"]


async def test_a_search_ordered_by_id_is_in_the_order_of_ids_however_many_match(
    client, hosted, root
):
    # A hundred ids begin with what is searched for, which ranks them first; the one
    # that comes first by its id only contains it.
    for number in range(100):
        await push(client, root, nupkg(f"Hello.N{number:03}", "1.0.0"))
    await push(client, root, nupkg("Aa.Hello", "1.0.0"))

    answer = await get(
        client, root, "Search()", **{"$orderby": "Id", "searchTerm": "'hello'", "$top": "1"}
    )

    assert versions_of(answer) == [("Aa.Hello", "1.0.0")]
