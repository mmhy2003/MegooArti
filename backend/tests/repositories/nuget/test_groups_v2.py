"""NuGet's V2 protocol of a group: one feed of its members that serve V2, its hosted
members, V2 proxies and groups (E3, 7.3) — queries merged in the members' order, an id's
version once, the page cut by the group, with the group's own addresses."""

from xml.etree import ElementTree

import pytest

from tests.accounts import error_code
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg

GROUP = "/repository/nuget-all"
BASE = "https://test/repository/nuget-all/"
REMOTE = "http://remote.test/api/v2/"
ATOM = "{http://www.w3.org/2005/Atom}"
D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
M = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
PUSHED = "Pushed here."
FETCHED = nupkg("MegooArti.Hello", "3.0.0", description="On the feed.")


def entry(package_id: str, version: str, description: str = "On the feed.") -> str:
    """An entry as the community feed writes one."""
    address = f"{REMOTE}Packages(Id='{package_id}',Version='{version}')"
    return (
        f"<entry><id>{address}</id>"
        f'<link rel="edit" title="V2FeedPackage" href="{address}" />'
        f'<title type="text">{package_id}</title>'
        f'<content type="application/zip" src="{REMOTE}package/{package_id}/{version}" />'
        f"<m:properties><d:Id>{package_id}</d:Id><d:Version>{version}</d:Version>"
        f"<d:NormalizedVersion>{version}</d:NormalizedVersion>"
        f"<d:Description>{description}</d:Description></m:properties></entry>"
    )


def feed(*entries: str, count: int | None = None, next_page: str = "") -> bytes:
    counted = f"<m:count>{count}</m:count>" if count is not None else ""
    following = f'<link rel="next" href="{next_page}" />' if next_page else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<feed xml:base="{REMOTE}" xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        f"{counted}<id>{REMOTE}Packages</id>{''.join(entries)}{following}</feed>"
    ).encode()


def entries(answer) -> list[tuple[str, str, str, str]]:
    """Each entry's id, normalized version, description and package address."""
    assert answer.status_code == 200, answer.text
    root = ElementTree.fromstring(answer.content)
    found = root.findall(f"{ATOM}entry") if root.tag == f"{ATOM}feed" else [root]
    listed = []
    for one in found:
        properties = one.find(f"{M}properties")
        listed.append(
            (
                properties.findtext(f"{D}Id"),
                properties.findtext(f"{D}NormalizedVersion"),
                properties.findtext(f"{D}Description"),
                one.find(f"{ATOM}content").get("src"),
            )
        )
    return listed


def next_link(answer) -> str | None:
    root = ElementTree.fromstring(answer.content)
    links = [link.get("href") for link in root.findall(f"{ATOM}link") if link.get("rel") == "next"]
    return links[0] if links else None


async def make(client, root, **body) -> None:
    answer = await client.post(
        "/api/v1/repositories", json={"format": "nuget", **body}, headers=root
    )
    assert answer.status_code == 201, answer.text


@pytest.fixture
async def group(client, hosted, root, fake_remote):
    """`nuget-all`: a hosted repository with MegooArti.Hello 1.0.0 and 2.0.0; a V2 proxy
    of a feed with its 1.0.0 and 3.0.0, and Choco.Thing 1.0.0; a V3 proxy, which serves
    no V2 and is left out of it."""
    for version in ("1.0.0", "2.0.0"):
        package = nupkg("MegooArti.Hello", version, description=PUSHED)
        assert (await push(client, root, package)).status_code == 201
    await make(
        client,
        root,
        name="choco",
        type="proxy",
        format_config={"protocol": "v2"},
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
    )
    await make(
        client,
        root,
        name="nuget-org",
        type="proxy",
        proxy={"remote_url": "http://v3.test/v3/index.json"},
    )
    await make(
        client,
        root,
        name="nuget-all",
        type="group",
        group={"members": ["nuget-hosted", "choco", "nuget-org"]},
    )
    hello = [entry("MegooArti.Hello", "1.0.0"), entry("MegooArti.Hello", "3.0.0")]
    fake_remote.files["api/v2/FindPackagesById()"] = feed(*hello, count=2)
    fake_remote.files["api/v2/Search()"] = feed(*hello, entry("Choco.Thing", "1.0.0"), count=3)
    fake_remote.files["api/v2/Packages(Id='MegooArti.Hello',Version='3.0.0')"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<entry xml:base="http://remote.test/api/v2/" xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        + entry("MegooArti.Hello", "3.0.0").removeprefix("<entry>")
    ).encode()
    fake_remote.files["api/v2/package/MegooArti.Hello/3.0.0"] = FETCHED
    return fake_remote


async def get(client, root, path: str, **arguments):
    return await client.get(f"{GROUP}/{path}", params=arguments, headers=root)


def asked(remote, path: str) -> list[str]:
    return [seen["query"] for seen in remote.requests if seen["path"] == f"/api/v2/{path}"]


async def test_the_root_and_metadata_are_the_groups_own(client, root, group):
    service = await get(client, root, "")
    metadata = await get(client, root, "$metadata")

    assert f'xml:base="{BASE}"'.encode() in service.content
    assert b'FunctionImport Name="FindPackagesById"' in metadata.content
    assert group.requests == []


async def test_a_query_is_merged_in_the_members_order_an_ids_version_once(client, root, group):
    answer = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")

    assert [(one[0], one[1], one[2]) for one in entries(answer)] == [
        ("MegooArti.Hello", "1.0.0", PUSHED),  # the first member's
        ("MegooArti.Hello", "2.0.0", PUSHED),
        ("MegooArti.Hello", "3.0.0", "On the feed."),
    ]
    assert [one[3] for one in entries(answer)] == [
        f"{BASE}package/MegooArti.Hello/{version}" for version in ("1.0.0", "2.0.0", "3.0.0")
    ]
    assert "remote.test" not in answer.text
    assert "/repository/nuget-hosted/" not in answer.text
    assert "/repository/choco/" not in answer.text


async def test_a_page_is_cut_by_the_group_and_leads_to_the_next(client, root, group):
    first = await get(client, root, "Search()", searchTerm="''", **{"$top": "2"})
    following = await client.get(next_link(first).removeprefix("https://test"), headers=root)
    counted = await get(client, root, "Search()/$count", searchTerm="''")

    assert [(one[0], one[1]) for one in entries(first)] == [
        ("MegooArti.Hello", "1.0.0"),
        ("MegooArti.Hello", "2.0.0"),
    ]
    assert next_link(first) == f"{BASE}Search()?searchTerm=''&$top=2&$skip=2"
    assert [(one[0], one[1]) for one in entries(following)] == [
        ("MegooArti.Hello", "3.0.0"),
        ("Choco.Thing", "1.0.0"),
    ]
    assert next_link(following) is None
    # Each member is asked for the page's end and one more, from the first.
    assert asked(group, "Search()")[0] == "searchTerm=''&$skip=0&$top=3"
    # Two of the hosted repository's, three of the feed's, less the one both have.
    assert counted.text == "4"


async def test_an_entry_is_the_first_members_that_has_it(client, root, group):
    pushed = await get(client, root, "Packages(Id='megooarti.hello',Version='1.0.0')")
    fetched = await get(client, root, "Packages(Id='MegooArti.Hello',Version='3.0.0')")
    missing = await get(client, root, "Packages(Id='MegooArti.Hello',Version='9.0.0')")

    assert entries(pushed)[0][2] == PUSHED
    assert entries(fetched)[0][3] == f"{BASE}package/MegooArti.Hello/3.0.0"
    assert missing.status_code == 404


async def test_a_package_is_the_first_members_that_has_it(client, root, group):
    pushed = await get(client, root, "package/MegooArti.Hello/1.0.0")
    fetched = await get(client, root, "package/MegooArti.Hello/3.0.0")

    assert pushed.content == nupkg("MegooArti.Hello", "1.0.0", description=PUSHED)
    assert fetched.content == FETCHED


async def test_each_protocol_is_asked_of_the_members_that_serve_it(client, root, group):
    await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")
    await get(client, root, "v3/package/megooarti.hello/index.json")

    hosts = {seen["host"] for seen in group.requests}
    # The V2 proxy is asked V2's query, and not V3's; the V3 proxy V3's, and not V2's.
    assert asked(group, "FindPackagesById()")
    assert not [seen for seen in group.requests if seen["path"].startswith("/api/v2/v3")]
    assert not [
        seen for seen in group.requests if seen["host"] == "v3.test" and "Packages" in seen["path"]
    ]
    assert "v3.test" in hosts


async def test_a_member_that_cannot_be_asked_is_passed_over(client, root, group):
    group.down = True

    answer = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")

    assert [(one[0], one[1]) for one in entries(answer)] == [
        ("MegooArti.Hello", "1.0.0"),
        ("MegooArti.Hello", "2.0.0"),
    ]


async def test_a_feeds_next_page_is_followed_for_the_entries_asked_for(client, root, group):
    group.files["api/v2/FindPackagesById()"] = feed(
        entry("MegooArti.Hello", "3.0.0"),
        next_page=f"{REMOTE}FindPackagesById?id='MegooArti.Hello'&$skiptoken='3.0.0'",
    )
    group.files["api/v2/FindPackagesById"] = feed(entry("MegooArti.Hello", "4.0.0"))

    answer = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")

    assert [one[1] for one in entries(answer)] == ["1.0.0", "2.0.0", "3.0.0", "4.0.0"]
    assert asked(group, "FindPackagesById") == ["id='MegooArti.Hello'&$skiptoken='3.0.0'"]


async def test_a_group_in_a_group_is_one_feed_too(client, root, group):
    await make(client, root, name="nuget-outer", type="group", group={"members": ["nuget-all"]})

    inner = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")
    outer = await client.get(
        "/repository/nuget-outer/FindPackagesById()",
        params={"id": "'MegooArti.Hello'"},
        headers=root,
    )

    assert [one[:3] for one in entries(outer)] == [one[:3] for one in entries(inner)]
    assert {one[3] for one in entries(outer)} == {
        f"https://test/repository/nuget-outer/package/MegooArti.Hello/{version}"
        for version in ("1.0.0", "2.0.0", "3.0.0")
    }


async def test_a_query_no_client_sends_is_refused_by_the_group(client, root, group):
    answer = await get(client, root, "Packages()", **{"$filter": "Title eq 'x'"})

    assert (answer.status_code, error_code(answer)) == (400, "unsupported_query")
    assert group.requests == []
