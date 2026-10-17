"""A proxy of a V2 feed, as the Chocolatey community feed and the PowerShell Gallery are:
its queries passed on as they came, its answers with the proxy's addresses, kept by the
whole query; its packages kept where pushed ones are."""

import pytest

from megooarti.repositories.nuget import proxied_v2
from tests.accounts import error_code
from tests.repositories.nuget.packages import nupkg

PROXY = "/repository/choco"
BASE = "https://test/repository/choco/"
REMOTE = "http://remote.test/api/v2/"
PACKAGE = nupkg("Choco.Thing", "1.0.0", description="A thing.")


def entry(version: str, *, root: str = REMOTE) -> str:
    """An entry as the community feed writes one: some addresses relative to its root."""
    address = f"{root}Packages(Id='Choco.Thing',Version='{version}')"
    return (
        f"<entry><id>{address}</id>"
        f'<link rel="edit-media" title="V2FeedPackage" '
        f"href=\"Packages(Id='Choco.Thing',Version='{version}')/$value\" />"
        f'<link rel="edit" title="V2FeedPackage" href="{address}" />'
        '<title type="text">Choco.Thing</title>'
        f'<content type="application/zip" src="{root}package/Choco.Thing/{version}" />'
        "<m:properties><d:Version>1.0.0</d:Version>"
        "<d:GalleryDetailsUrl>http://remote.test/packages/Choco.Thing</d:GalleryDetailsUrl>"
        "</m:properties></entry>"
    )


def feed(*entries: str, root: str = REMOTE, next_page: str = "") -> bytes:
    next_link = f'<link rel="next" href="{next_page}" />' if next_page else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<feed xml:base="{root}" xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        f"<id>{root.rstrip('/')}/FindPackagesById</id>{''.join(entries)}{next_link}</feed>"
    ).encode()


async def make(client, root, name: str = "choco", **proxy) -> dict:
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": name,
            "format": "nuget",
            "type": "proxy",
            "format_config": {"protocol": "v2"},
            "proxy": {"remote_url": REMOTE.rstrip("/"), **proxy},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text
    return made.json()


@pytest.fixture
async def remote(client, root, fake_remote):
    await make(client, root)
    fake_remote.files["api/v2/FindPackagesById()"] = feed(
        entry("1.0.0"), next_page=f"{REMOTE}FindPackagesById?id='Choco.Thing'&$skiptoken='x'"
    )
    fake_remote.files["api/v2/Packages(Id='Choco.Thing',Version='1.0.0')"] = (
        '<?xml version="1.0" encoding="utf-8"?>' + entry("1.0.0")
    ).encode()
    fake_remote.files["api/v2/Search()"] = feed(entry("1.0.0"))
    fake_remote.files["api/v2/$metadata"] = b"<edmx:Edmx>the feed's own</edmx:Edmx>"
    fake_remote.files["api/v2/package/Choco.Thing/1.0.0"] = PACKAGE
    return fake_remote


def asked(remote, path: str) -> list[str]:
    return [seen["query"] for seen in remote.requests if seen["path"] == f"/api/v2/{path}"]


async def test_the_root_is_the_proxys_own(client, root, remote):
    answer = await client.get(f"{PROXY}/", headers=root)

    assert b'<collection href="Packages">' in answer.content
    assert f'xml:base="{BASE}"'.encode() in answer.content
    assert remote.requests == []


async def test_a_query_is_passed_on_as_it_came_with_the_proxys_addresses(client, root, remote):
    query = "id='Choco.Thing'&semVerLevel=2.0.0"

    answer = await client.get(f"{PROXY}/FindPackagesById()?{query}", headers=root)

    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("application/atom+xml")
    assert asked(remote, "FindPackagesById()") == [query]
    text = answer.text
    assert f'xml:base="{BASE}"' in text
    assert f"<id>{BASE}Packages(Id='Choco.Thing',Version='1.0.0')</id>" in text
    assert f'src="{BASE}package/Choco.Thing/1.0.0"' in text
    assert f"href=\"{BASE}FindPackagesById?id='Choco.Thing'&$skiptoken='x'\"" in text
    assert "href=\"Packages(Id='Choco.Thing',Version='1.0.0')/$value\"" in text
    # What is not under the feed's root is left as it is.
    assert "http://remote.test/packages/Choco.Thing" in text


async def test_an_answer_is_kept_by_its_whole_query(client, root, remote):
    for query in ("id='Choco.Thing'", "id='Choco.Thing'", "id='choco.thing'"):
        await client.get(f"{PROXY}/FindPackagesById()?{query}", headers=root)
    await client.get(f"{PROXY}/Packages(Id='Choco.Thing',Version='1.0.0')", headers=root)

    assert asked(remote, "FindPackagesById()") == ["id='Choco.Thing'", "id='choco.thing'"]
    assert len(asked(remote, "Packages(Id='Choco.Thing',Version='1.0.0')")) == 1


async def test_what_the_feed_answered_is_given_while_it_cannot_be_reached(
    client, root, fake_remote
):
    await make(client, root, "choco-fresh", metadata_max_age_minutes=0)
    fake_remote.files["api/v2/FindPackagesById()"] = feed(entry("1.0.0"))
    address = "/repository/choco-fresh/FindPackagesById()?id='Choco.Thing'"
    await client.get(address, headers=root)
    fake_remote.down = True

    answer = await client.get(address, headers=root)

    assert answer.status_code == 200
    assert "https://test/repository/choco-fresh/package/Choco.Thing/1.0.0" in answer.text


async def test_a_search_is_passed_on_every_time(client, root, remote):
    query = "$filter=IsLatestVersion&searchTerm='thing'&includePrerelease=false"
    for _ in range(2):
        answer = await client.get(f"{PROXY}/Search()?{query}", headers=root)

    assert f'src="{BASE}package/Choco.Thing/1.0.0"' in answer.text
    assert asked(remote, "Search()") == [query, query]


async def test_metadata_is_the_feeds(client, root, remote):
    answer = await client.get(f"{PROXY}/$metadata", headers=root)

    assert answer.content == b"<edmx:Edmx>the feed's own</edmx:Edmx>"


async def test_a_package_is_kept_where_a_pushed_one_is_and_read_as_one(client, root, remote):
    for _ in range(2):
        fetched = await client.get(f"{PROXY}/package/Choco.Thing/1.0.0", headers=root)
    components = (await client.get("/api/v1/content/choco/components", headers=root)).json()
    kept = await client.get(
        f"{PROXY}/v3/package/choco.thing/1.0.0/choco.thing.1.0.0.nupkg", headers=root
    )

    assert fetched.content == PACKAGE
    assert len(asked(remote, "package/Choco.Thing/1.0.0")) == 1
    assert [(item["name"], item["version"]) for item in components["items"]] == [
        ("Choco.Thing", "1.0.0")
    ]
    # Kept, and not asked for again: a V2 proxy serves no V3 address.
    assert kept.status_code == 404


@pytest.mark.parametrize(
    "path",
    ["index.json", "v3/package/choco.thing/index.json", "GetUpdates()", "package/x/not-a-version"],
)
async def test_what_v2_does_not_serve_is_not_asked_of_the_feed(client, root, remote, path):
    answer = await client.get(f"{PROXY}/{path}", headers=root)

    assert answer.status_code == 404
    assert remote.requests == []


async def test_a_proxy_takes_no_push_and_keeps_its_protocol(client, root, remote):
    pushed = await client.put(
        f"{PROXY}/",
        files={"package": ("x.nupkg", PACKAGE, "application/octet-stream")},
        headers=root,
    )
    changed = await client.put(
        "/api/v1/repositories/choco", json={"format_config": {"protocol": "v3"}}, headers=root
    )

    assert pushed.status_code == 405
    assert (changed.status_code, error_code(changed)) == (422, "validation_error")


async def test_an_answer_that_is_not_utf8_is_said_to_be_so(client, root, remote):
    remote.files["api/v2/FindPackagesById()"] = b"<feed>\xff</feed>"

    answer = await client.get(f"{PROXY}/FindPackagesById()?id='x'", headers=root)

    assert (answer.status_code, error_code(answer)) == (502, "remote_unavailable")


def test_the_root_an_answer_names_is_made_the_proxys_too():
    # The Gallery names its root without a slash, and the feed may be given otherwise.
    data = feed(
        entry("1.0.0", root="https://www.remote.test/api/v2/"),
        root="https://www.remote.test/api/v2",
    )

    rewritten = proxied_v2.rewrite(data, REMOTE, BASE).decode()

    assert 'xml:base="https://test/repository/choco"' in rewritten
    assert f'src="{BASE}package/Choco.Thing/1.0.0"' in rewritten
    assert "remote.test/api" not in rewritten
