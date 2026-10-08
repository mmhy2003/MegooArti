import base64
import hashlib

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from tests.accounts import error_code
from tests.repositories.pypi.conftest import (
    FILES_HOST,
    REMOTE,
    content_of,
    create,
    link_to,
    links,
    remote_link,
    remote_page,
)

PROXY = "/repository/upstream"
PAGE = f"{PROXY}/simple/requests/"
OLD = "requests-2.30.0.tar.gz"
WHEEL = "requests-2.31.0-py3-none-any.whl"
SDIST = "requests-2.31.0.tar.gz"
WHEEL_URL = f"{PROXY}/packages/requests/2.31.0/{WHEEL}"
METADATA = b"Metadata-Version: 2.1\nName: requests\nVersion: 2.31.0\n"


def asked(remote) -> list[tuple[str, str]]:
    return [(seen["host"], seen["path"]) for seen in remote.requests]


@pytest.fixture
def remote(fake_remote, upstream):
    """The remote index has a page for requests; its files are on another host."""
    described = f'data-core-metadata="sha256={hashlib.sha256(METADATA).hexdigest()}"'
    fake_remote.files["pypi/simple/requests/"] = remote_page(
        "requests",
        OLD,
        remote_link(WHEEL, 'data-requires-python="&gt;=3.7"', described),
        remote_link(SDIST, 'data-requires-python="&gt;=3.7"', 'data-yanked="withdrawn"'),
    )
    for filename in (OLD, WHEEL, SDIST):
        fake_remote.files[f"packages/{filename}"] = content_of(filename)
    fake_remote.files[f"packages/{WHEEL}.metadata"] = METADATA
    return fake_remote


async def test_a_page_is_written_from_the_remotes_links_and_points_here(client, root, remote):
    first = await client.get(PAGE, headers=root)
    second = await client.get(PAGE, headers=root)

    assert first.status_code == 200, first.text
    digest = hashlib.sha256(METADATA).hexdigest()
    assert links(first) == [
        link_to("requests", "2.30.0", OLD),
        link_to(
            "requests",
            "2.31.0",
            WHEEL,
            **{
                "data-requires-python": ">=3.7",
                "data-dist-info-metadata": f"sha256={digest}",
                "data-core-metadata": f"sha256={digest}",
            },
        ),
        link_to(
            "requests",
            "2.31.0",
            SDIST,
            **{"data-requires-python": ">=3.7", "data-yanked": "withdrawn"},
        ),
    ]
    assert "files.test" not in first.text and "remote.test" not in first.text
    assert second.content == first.content
    assert asked(remote) == [("remote.test", "/pypi/simple/requests/")]


async def test_the_page_is_answered_as_content_without_a_length(client, root, remote):
    first = await client.get(PAGE, headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(PAGE, headers={**root, "If-None-Match": etag})
    headed = await client.head(PAGE, headers=root)

    assert first.headers["Content-Type"] == "text/html; charset=utf-8"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert first.headers["Accept-Ranges"] == "none"
    assert "Content-Length" not in first.headers
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (headed.status_code, headed.content, headed.headers["ETag"]) == (200, b"", etag)
    assert "Content-Length" not in headed.headers


async def test_a_file_is_fetched_from_where_the_remote_keeps_it_and_cached(
    client, root, remote, db
):
    first = await client.get(WHEEL_URL, headers=root)
    second = await client.get(WHEEL_URL, headers={**root, "Range": "bytes=0-3"})

    data = content_of(WHEEL)
    assert (first.status_code, first.content) == (200, data)
    assert first.headers["Content-Type"] == "application/octet-stream"
    assert first.headers["ETag"] == f'"{hashlib.sha256(data).hexdigest()}"'
    assert (second.status_code, second.content) == (206, data[:4])
    assert asked(remote) == [
        ("remote.test", "/pypi/simple/requests/"),
        ("files.test", f"/packages/{WHEEL}"),
    ]
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "requests", "2.31.0")


async def test_a_link_on_the_page_leads_to_the_file(client, root, remote):
    page = await client.get(PAGE, headers=root)
    href = links(page)[1][0]["href"]

    fetched = await client.get(str(page.url.join(href)), headers=root)

    assert (fetched.status_code, fetched.content) == (200, content_of(WHEEL))


async def test_a_file_asked_for_by_head_or_by_range_first_is_fetched_whole(client, root, remote):
    headed = await client.head(WHEEL_URL, headers=root)
    part = await client.get(
        f"{PROXY}/packages/requests/2.31.0/{SDIST}", headers={**root, "Range": "bytes=0-3"}
    )

    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Content-Length"] == str(len(content_of(WHEEL)))
    assert (part.status_code, part.content) == (206, content_of(SDIST)[:4])
    assert [seen["method"] for seen in remote.requests] == ["GET", "GET", "GET"]


async def test_a_file_that_is_not_the_one_the_page_describes_is_not_served(
    client, root, remote, db
):
    remote.files[f"packages/{WHEEL}"] = b"replaced at the remote"

    response = await client.get(WHEEL_URL, headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert list(await db.scalars(select(Asset.path))) == ["simple/requests"]


@pytest.mark.parametrize(
    "path",
    [
        "packages/requests/2.31.0/requests-2.31.1.tar.gz",  # not on the page
        f"packages/requests/9.9.9/{WHEEL}",  # on the page, under another version
        "packages/requests/2.31.0/urllib3-2.0.0.tar.gz",  # another project's file
        f"packages/requests/2.30.0/{OLD}.metadata",  # the remote has no metadata for it
    ],
)
async def test_a_file_the_page_does_not_list_is_not_found(client, root, remote, path):
    response = await client.get(f"{PROXY}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")
    assert asked(remote) == [("remote.test", "/pypi/simple/requests/")]


async def test_a_metadata_file_is_fetched_from_beside_its_file(client, root, remote):
    first = await client.get(f"{WHEEL_URL}.metadata", headers=root)
    second = await client.get(f"{WHEEL_URL}.metadata", headers=root)

    assert (first.status_code, first.content, second.content) == (200, METADATA, METADATA)
    assert first.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert asked(remote) == [
        ("remote.test", "/pypi/simple/requests/"),
        ("files.test", f"/packages/{WHEEL}.metadata"),
    ]


async def test_a_metadata_file_must_match_its_hash_too(client, root, remote):
    remote.files[f"packages/{WHEEL}.metadata"] = b"Name: something-else\n"

    response = await client.get(f"{WHEEL_URL}.metadata", headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")


async def test_the_root_index_lists_what_has_been_cached_and_asks_nobody(client, root, remote):
    before = await client.get(f"{PROXY}/simple/", headers=root)
    await client.get(PAGE, headers=root)  # a page alone is not a project held
    await client.get(WHEEL_URL, headers=root)
    remote.requests.clear()

    after = await client.get(f"{PROXY}/simple/", headers=root)

    assert links(before) == []
    assert links(after) == [({"href": "requests/"}, "requests")]
    assert remote.requests == []


async def test_a_page_is_asked_about_again_and_a_file_never(client, root, db, fake_remote):
    ages = {"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": 0}
    await create(db, "eager", type="proxy", proxy=ages)
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)
    file_url = f"/repository/eager/packages/requests/2.30.0/{OLD}"
    for _ in range(2):
        await client.get("/repository/eager/simple/requests/", headers=root)
        await client.get(file_url, headers=root)
    before = await client.get("/repository/eager/simple/requests/", headers=root)

    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, SDIST)
    after = await client.get(
        "/repository/eager/simple/requests/",
        headers={**root, "If-None-Match": before.headers["ETag"]},
    )

    assert [path for _, path in asked(fake_remote)].count(f"/packages/{OLD}") == 1
    assert (after.status_code, [text for _, text in links(after)]) == (200, [OLD, SDIST])
    assert after.headers["ETag"] != before.headers["ETag"]


async def test_what_the_remote_lacks_is_not_found_and_remembered(client, root, remote):
    first = await client.get(f"{PROXY}/simple/no-such-project/", headers=root)
    again = await client.get(f"{PROXY}/simple/no-such-project/", headers=root)
    its_file = await client.get(
        f"{PROXY}/packages/no-such-project/1.0/no_such_project-1.0.tar.gz", headers=root
    )

    for response in (first, again, its_file):
        assert (response.status_code, error_code(response)) == (404, "not_found")
    assert asked(remote) == [("remote.test", "/pypi/simple/no-such-project/")]


async def test_what_is_cached_is_served_while_the_remote_is_down(client, root, db, fake_remote):
    await create(
        db, "eager", type="proxy", proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0}
    )
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, SDIST)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)
    page = await client.get("/repository/eager/simple/requests/", headers=root)
    await client.get(f"/repository/eager/packages/requests/2.30.0/{OLD}", headers=root)
    fake_remote.down = True

    still = await client.get("/repository/eager/simple/requests/", headers=root)
    cached = await client.get(f"/repository/eager/packages/requests/2.30.0/{OLD}", headers=root)
    not_cached = await client.get(
        f"/repository/eager/packages/requests/2.31.0/{SDIST}", headers=root
    )
    unknown = await client.get("/repository/eager/simple/flask/", headers=root)

    assert (still.status_code, still.content) == (200, page.content)
    assert cached.content == content_of(OLD)
    assert (not_cached.status_code, error_code(not_cached)) == (502, "remote_unavailable")
    assert (unknown.status_code, error_code(unknown)) == (502, "remote_unavailable")


@pytest.mark.parametrize(
    ("asked_for", "location"),
    [
        ("simple", "simple/"),
        ("simple/requests", "requests/"),
        ("simple/Requests/", "../requests/"),
        ("simple/zope.interface", "zope-interface/"),
    ],
)
async def test_a_page_has_one_address_on_a_proxy_too(client, root, remote, asked_for, location):
    moved = await client.get(f"{PROXY}/{asked_for}", headers=root)

    assert (moved.status_code, moved.headers["Location"]) == (301, location)
    assert remote.requests == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", ""),
        ("PUT", "simple/requests/"),
        ("DELETE", f"packages/requests/2.31.0/{WHEEL}"),
        ("PUT", f"packages/requests/2.31.0/{WHEEL}"),
        ("POST", "simple/"),
    ],
)
async def test_a_proxy_cannot_be_written_to(client, root, remote, method, path):
    response = await client.request(method, f"{PROXY}/{path}", content=b"x", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
    assert remote.requests == []


@pytest.mark.parametrize("path", ["", "pypi/requests/json", "packages/requests", "simple/a/b/"])
async def test_addresses_that_mean_nothing_on_a_proxy(client, root, remote, path):
    response = await client.get(f"{PROXY}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")
    assert remote.requests == []


@pytest.mark.parametrize(
    ("configured", "page_path"),
    [
        ("http://remote.test/pypi", "/pypi/simple/requests/"),
        ("http://remote.test/pypi/", "/pypi/simple/requests/"),
        ("http://remote.test/pypi/simple", "/pypi/simple/requests/"),
        ("http://remote.test/pypi/simple/", "/pypi/simple/requests/"),
        ("http://remote.test/root/pypi/+simple", "/root/pypi/+simple/requests/"),
        ("http://remote.test", "/simple/requests/"),
    ],
)
async def test_the_remote_is_an_index_or_its_root(
    client, root, db, fake_remote, configured, page_path
):
    await create(db, "other", type="proxy", proxy={"remote_url": configured})
    fake_remote.files[page_path.lstrip("/")] = remote_page("requests", OLD)

    response = await client.get("/repository/other/simple/requests/", headers=root)

    assert [text for _, text in links(response)] == [OLD]
    assert asked(fake_remote) == [("remote.test", page_path)]


async def test_links_relative_to_the_remotes_page_are_followed(client, root, db, fake_remote):
    # As devpi, Artifactory and Nexus write them: the files are on the index's own host.
    await create(
        db, "devpi", type="proxy", proxy={"remote_url": "http://remote.test/root/pypi/+simple"}
    )
    digest = hashlib.sha256(content_of(OLD)).hexdigest()
    link = f'<a href="../../+f/ab/cd/{OLD}#sha256={digest}">{OLD}</a>'
    fake_remote.files["root/pypi/+simple/requests/"] = remote_page("requests", link)
    fake_remote.files[f"root/pypi/+f/ab/cd/{OLD}"] = content_of(OLD)

    response = await client.get(f"/repository/devpi/packages/requests/2.30.0/{OLD}", headers=root)

    assert response.content == content_of(OLD)
    assert asked(fake_remote)[-1] == ("remote.test", f"/root/pypi/+f/ab/cd/{OLD}")


async def test_the_remotes_credential_is_not_sent_to_the_host_of_its_files(
    admin_client, fake_remote
):
    private = {
        "name": "private",
        "format": "pypi",
        "type": "proxy",
        "proxy": {
            "remote_url": REMOTE,
            "remote_auth": {"type": "basic", "username": "robot", "secret": "s3cret"},
        },
    }
    await admin_client.post("/api/v1/repositories", json=private)
    same_host = remote_link("requests-2.29.0.tar.gz", at="http://remote.test/pypi")
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, same_host)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)
    fake_remote.files["pypi/packages/requests-2.29.0.tar.gz"] = content_of("requests-2.29.0.tar.gz")

    for version, filename in (("2.30.0", OLD), ("2.29.0", "requests-2.29.0.tar.gz")):
        response = await admin_client.get(
            f"/repository/private/packages/requests/{version}/{filename}"
        )
        assert response.status_code == 200, response.text

    expected = "Basic " + base64.b64encode(b"robot:s3cret").decode()
    sent = [(seen["host"], seen["headers"].get("authorization")) for seen in fake_remote.requests]
    assert sent == [("remote.test", expected), ("files.test", None), ("remote.test", expected)]


@pytest.mark.parametrize(
    "address",
    ["http://127.0.0.1:8000", "http://169.254.169.254", "http://10.0.0.5", "http://localhost"],
)
async def test_a_page_cannot_send_the_proxy_to_an_internal_address(
    client, root, upstream, fake_remote, db, address
):
    fake_remote.files["pypi/simple/requests/"] = remote_page(
        "requests", remote_link(OLD, at=address)
    )
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)

    page = await client.get(PAGE, headers=root)
    response = await client.get(f"{PROXY}/packages/requests/2.30.0/{OLD}", headers=root)

    assert [text for _, text in links(page)] == [OLD]  # listed; fetching it is what is refused
    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert asked(fake_remote) == [("remote.test", "/pypi/simple/requests/")]
    assert list(await db.scalars(select(Asset.path))) == ["simple/requests"]


async def test_nothing_a_remote_writes_reaches_the_page_but_what_is_read_from_its_links(
    client, root, upstream, fake_remote
):
    hostile = (
        "<script>alert(1)</script><img src=x onerror=alert(2)>"
        + remote_link(OLD, 'data-requires-python="&quot;&gt;&lt;script&gt;alert(3)&lt;/script&gt;"')
        + '<a href="javascript:alert(4)">requests-9.tar.gz</a>'
        + f'<a href="{FILES_HOST}/packages/evil-1.0.tar.gz" onclick="alert(5)">evil-1.0.tar.gz</a>'
    )
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", hostile)

    page = await client.get(PAGE, headers=root)

    assert "<script>" not in page.text and "onerror" not in page.text and "onclick" not in page.text
    assert links(page) == [
        link_to(
            "requests", "2.30.0", OLD, **{"data-requires-python": '"><script>alert(3)</script>'}
        )
    ]


async def test_a_page_read_back_in_several_pieces_lists_every_file(
    client, root, upstream, fake_remote
):
    filenames = [f"requests-1.{minor}.0.tar.gz" for minor in range(16_000)]
    page = remote_page("requests", *filenames)
    assert len(page) > 2 * 1024 * 1024  # over two pieces
    fake_remote.files["pypi/simple/requests/"] = page

    response = await client.get(PAGE, headers=root)

    assert [text for _, text in links(response)] == filenames


async def test_a_file_listed_twice_is_written_once(client, root, upstream, fake_remote):
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, SDIST, OLD)

    response = await client.get(PAGE, headers=root)

    assert [text for _, text in links(response)] == [OLD, SDIST]


async def invalidate(db, name: str = "upstream") -> None:
    await service.invalidate_cache(db, await service.get_repository(db, name))
    await db.commit()


async def test_a_cached_file_is_fetched_again_after_the_cache_is_invalidated(
    client, root, remote, db
):
    await client.get(WHEEL_URL, headers=root)
    rebuilt = b"rebuilt at the remote"
    described = f'data-core-metadata="sha256={hashlib.sha256(METADATA).hexdigest()}"'
    remote.files["pypi/simple/requests/"] = remote_page(
        "requests", remote_link(WHEEL, described, data=rebuilt)
    )
    remote.files[f"packages/{WHEEL}"] = rebuilt
    untouched = await client.get(WHEEL_URL, headers=root)

    await invalidate(db)
    page = await client.get(PAGE, headers=root)
    after = await client.get(WHEEL_URL, headers=root)
    remote.requests.clear()
    again = await client.get(WHEEL_URL, headers=root)

    assert untouched.content == content_of(WHEEL)  # a cached file is not asked about
    assert links(page)[0][0]["href"].endswith(f"#sha256={hashlib.sha256(rebuilt).hexdigest()}")
    assert (after.content, again.content) == (rebuilt, rebuilt)  # what the page describes
    assert remote.requests == []  # and once checked, it is not asked about again


async def test_an_invalidated_file_that_has_not_changed_is_not_downloaded_again(
    client, root, remote, db
):
    await client.get(WHEEL_URL, headers=root)
    await invalidate(db)
    remote.requests.clear()

    first = await client.get(WHEEL_URL, headers=root)
    second = await client.get(WHEEL_URL, headers=root)

    assert (first.content, second.content) == (content_of(WHEEL), content_of(WHEEL))
    answered = [(seen["host"], "if-none-match" in seen["headers"]) for seen in remote.requests]
    assert answered == [("remote.test", True), ("files.test", True)]  # both said "unchanged"


async def test_an_invalidated_file_is_kept_when_the_remote_cannot_replace_it(
    client, root, remote, db
):
    await client.get(WHEEL_URL, headers=root)
    await invalidate(db)
    remote.files["pypi/simple/requests/"] = remote_page("requests", OLD)  # no longer listed

    dropped = await client.get(WHEEL_URL, headers=root)
    remote.down = True
    unreachable = await client.get(WHEEL_URL, headers=root)

    assert (dropped.status_code, dropped.content) == (200, content_of(WHEEL))
    assert (unreachable.status_code, unreachable.content) == (200, content_of(WHEEL))


async def test_a_page_with_a_link_that_cannot_be_read_still_lists_and_serves_the_rest(
    client, root, upstream, fake_remote
):
    broken = '<a href="http://[::1/requests-9.9.tar.gz">requests-9.9.tar.gz</a>'
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, broken, SDIST)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)

    page = await client.get(PAGE, headers=root)
    fetched = await client.get(f"{PROXY}/packages/requests/2.30.0/{OLD}", headers=root)

    assert [text for _, text in links(page)] == [OLD, SDIST]
    assert fetched.content == content_of(OLD)
