import hashlib

import pytest

from megooarti.repositories import service
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.pypi.conftest import (
    CONTENT_TYPE,
    content_of,
    create,
    form_body,
    link_to,
    links,
    remote_link,
    remote_page,
    upload,
    upload_fields,
)

GROUP = "/repository/everything"
OURS = "internal_tool-1.0.0.tar.gz"
THEIRS = "internal_tool-99.0.0.tar.gz"
PUBLIC = "requests-2.31.0.tar.gz"


@pytest.fixture
async def everything(db, index, upstream):
    """The hosted `pypi` and the proxy `upstream`, in that order."""
    return await create(db, "everything", type="group", group={"members": ["pypi", "upstream"]})


def names_on(response) -> list[str]:
    return [text for _, text in links(response)]


def asked(remote) -> list[tuple[str, str]]:
    return [(seen["host"], seen["path"]) for seen in remote.requests]


async def take_offline(db, name: str) -> None:
    repository = await service.get_repository(db, name)
    repository.online = False
    await db.commit()


def public_project(fake_remote, project: str, *filenames: str, index: str = "pypi") -> None:
    """Put a project on the fake remote: its page, and its files on the other host."""
    fake_remote.files[f"{index}/simple/{project}/"] = remote_page(project, *filenames)
    for filename in filenames:
        fake_remote.files[f"packages/{filename}"] = content_of(filename)


async def test_a_project_we_host_comes_from_us_and_the_remote_is_not_asked(
    client, root, everything, fake_remote
):
    await upload(client, root, OURS, requires_python=">=3.9")

    page = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    fetched = await client.get(str(page.url.join(links(page)[0][0]["href"])), headers=root)

    assert links(page) == [
        link_to("internal-tool", "1.0.0", OURS, **{"data-requires-python": ">=3.9"})
    ]
    assert fetched.url.path == f"{GROUP}/packages/internal-tool/1.0.0/{OURS}"  # through the group
    assert fetched.content == content_of(OURS)
    assert fake_remote.requests == []


async def test_a_project_only_the_remote_has_comes_through_the_proxy(
    client, root, everything, fake_remote
):
    public_project(fake_remote, "requests", PUBLIC)

    page = await client.get(f"{GROUP}/simple/requests/", headers=root)
    fetched = await client.get(str(page.url.join(links(page)[0][0]["href"])), headers=root)

    assert links(page) == [link_to("requests", "2.31.0", PUBLIC)]
    assert "Content-Length" not in page.headers  # written as it is sent
    assert fetched.url.path == f"{GROUP}/packages/requests/2.31.0/{PUBLIC}"
    assert fetched.content == content_of(PUBLIC)
    assert asked(fake_remote) == [
        ("remote.test", "/pypi/simple/requests/"),
        ("files.test", f"/packages/{PUBLIC}"),
    ]


async def test_a_public_project_cannot_add_files_to_a_name_we_host(
    client, root, everything, fake_remote
):
    # Dependency confusion: the same name on the public index, with a higher version.
    await upload(client, root, OURS)
    public_project(fake_remote, "internal-tool", THEIRS)

    page = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    theirs = await client.get(f"{GROUP}/packages/internal-tool/99.0.0/{THEIRS}", headers=root)
    described = await client.get(
        f"{GROUP}/packages/internal-tool/99.0.0/{THEIRS}.metadata", headers=root
    )

    assert names_on(page) == [OURS]
    for response in (theirs, described):
        assert (response.status_code, error_code(response)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_a_public_project_cannot_stand_in_for_a_file_we_host(
    client, root, db, index, upstream, fake_remote
):
    # The proxy is tried first here, and the remote has a file of the very same name.
    await create(db, "remote-first", type="group", group={"members": ["upstream", "pypi"]})
    await upload(client, root, OURS)
    fake_remote.files["pypi/simple/internal-tool/"] = remote_page(
        "internal-tool", remote_link(OURS, data=b"hostile")
    )
    fake_remote.files[f"packages/{OURS}"] = b"hostile"

    page = await client.get("/repository/remote-first/simple/internal-tool/", headers=root)
    fetched = await client.get(
        f"/repository/remote-first/packages/internal-tool/1.0.0/{OURS}", headers=root
    )

    assert links(page) == [link_to("internal-tool", "1.0.0", OURS)]  # with our hash
    assert fetched.content == content_of(OURS)
    assert fake_remote.requests == []


async def test_a_name_an_offline_repository_holds_is_not_answered_by_the_remote(
    client, root, everything, fake_remote, db
):
    await upload(client, root, OURS)
    public_project(fake_remote, "internal-tool", THEIRS)
    public_project(fake_remote, "requests", PUBLIC)
    await take_offline(db, "pypi")

    page = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    theirs = await client.get(f"{GROUP}/packages/internal-tool/99.0.0/{THEIRS}", headers=root)
    public = await client.get(f"{GROUP}/simple/requests/", headers=root)

    for response in (page, theirs):
        assert (response.status_code, error_code(response)) == (503, "repository_offline")
    assert names_on(public) == [PUBLIC]  # a name nobody here holds is still served
    assert asked(fake_remote) == [("remote.test", "/pypi/simple/requests/")]


async def test_a_name_held_behind_an_offline_group_is_not_answered_by_the_remote(
    client, root, db, index, upstream, fake_remote
):
    await create(db, "inner", type="group", group={"members": ["pypi"]})
    await create(db, "outer", type="group", group={"members": ["inner", "upstream"]})
    await upload(client, root, OURS)
    public_project(fake_remote, "internal-tool", THEIRS)
    await take_offline(db, "inner")

    response = await client.get("/repository/outer/simple/internal-tool/", headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")
    assert fake_remote.requests == []


async def test_an_offline_proxy_is_left_out(client, root, everything, fake_remote, db):
    await upload(client, root, OURS)
    public_project(fake_remote, "requests", PUBLIC)
    await take_offline(db, "upstream")

    ours = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    theirs = await client.get(f"{GROUP}/simple/requests/", headers=root)

    assert names_on(ours) == [OURS]
    assert (theirs.status_code, error_code(theirs)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_hosted_repositories_are_listed_together_and_the_earlier_one_wins(client, root, db):
    await create(db, "pypi")
    await create(db, "team")
    await create(db, "both", type="group", group={"members": ["pypi", "team"]})
    await upload(client, root, OURS)
    await upload(client, root, OURS, repository="team", data=b"the team's build")
    await upload(client, root, "internal_tool-2.0.0.tar.gz", repository="team")

    page = await client.get("/repository/both/simple/internal-tool/", headers=root)
    shared = await client.get(f"/repository/both/packages/internal-tool/1.0.0/{OURS}", headers=root)
    later = await client.get(
        "/repository/both/packages/internal-tool/2.0.0/internal_tool-2.0.0.tar.gz", headers=root
    )

    assert links(page) == [
        link_to("internal-tool", "1.0.0", OURS),  # the hash of the first repository's file
        link_to("internal-tool", "2.0.0", "internal_tool-2.0.0.tar.gz"),
    ]
    assert shared.content == content_of(OURS)
    assert later.content == content_of("internal_tool-2.0.0.tar.gz")


async def test_a_page_from_hosted_repositories_is_answered_like_any_content(
    client, root, everything
):
    await upload(client, root, OURS)
    first = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(
        f"{GROUP}/simple/internal-tool/", headers={**root, "If-None-Match": etag}
    )
    headed = await client.head(f"{GROUP}/simple/internal-tool/", headers=root)

    assert first.headers["Content-Type"] == "text/html; charset=utf-8"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, headed.status_code, headed.content) == (304, 200, b"")


@pytest.fixture
async def mirrors(db, fake_remote):
    """Proxies `first` and `second` of two indexes that both have requests, in one group."""
    await create(db, "first", type="proxy", proxy={"remote_url": "http://remote.test/a"})
    await create(db, "second", type="proxy", proxy={"remote_url": "http://remote.test/b"})
    shared = "requests-2.30.0.tar.gz"
    fake_remote.files["a/simple/requests/"] = remote_page(
        "requests", "requests-2.29.0.tar.gz", remote_link(shared, at="http://files.test/a")
    )
    fake_remote.files["b/simple/requests/"] = remote_page(
        "requests", remote_link(shared, at="http://files.test/b", data=b"b's build"), PUBLIC
    )
    fake_remote.files[f"a/packages/{shared}"] = content_of(shared)
    fake_remote.files[f"b/packages/{shared}"] = b"b's build"
    fake_remote.files[f"packages/{PUBLIC}"] = content_of(PUBLIC)
    return await create(db, "mirrors", type="group", group={"members": ["first", "second"]})


async def test_two_proxies_that_both_have_a_project_are_listed_together(
    client, root, mirrors, fake_remote
):
    page = await client.get("/repository/mirrors/simple/requests/", headers=root)
    again = await client.get(
        "/repository/mirrors/simple/requests/",
        headers={**root, "If-None-Match": page.headers["ETag"]},
    )
    shared = await client.get(
        "/repository/mirrors/packages/requests/2.30.0/requests-2.30.0.tar.gz", headers=root
    )
    theirs = await client.get(
        f"/repository/mirrors/packages/requests/2.31.0/{PUBLIC}", headers=root
    )

    # A file name both list is written once, as the earlier proxy describes it.
    assert links(page) == [
        link_to("requests", "2.29.0", "requests-2.29.0.tar.gz"),
        link_to("requests", "2.30.0", "requests-2.30.0.tar.gz"),
        link_to("requests", "2.31.0", PUBLIC),
    ]
    assert again.status_code == 304
    assert shared.content == content_of("requests-2.30.0.tar.gz")  # and served by that proxy
    assert theirs.content == content_of(PUBLIC)


async def test_a_proxy_that_cannot_answer_is_left_out(client, root, mirrors, fake_remote):
    del fake_remote.files["a/simple/requests/"]

    page = await client.get("/repository/mirrors/simple/requests/", headers=root)
    before = page.headers["ETag"]
    fake_remote.files["a/simple/flask/"] = remote_page("flask", "flask-3.0.0.tar.gz")
    only_first = await client.get("/repository/mirrors/simple/flask/", headers=root)

    assert names_on(page) == ["requests-2.30.0.tar.gz", PUBLIC]
    assert names_on(only_first) == ["flask-3.0.0.tar.gz"]
    assert only_first.headers["ETag"] != before


async def test_nobody_has_it(client, root, everything, fake_remote):
    missing = await client.get(f"{GROUP}/simple/no-such-project/", headers=root)
    fake_remote.down = True
    unreachable = await client.get(f"{GROUP}/simple/another-project/", headers=root)
    its_file = await client.get(
        f"{GROUP}/packages/another-project/1.0/another_project-1.0.tar.gz", headers=root
    )

    for response in (missing, unreachable, its_file):
        assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_a_group_inside_a_group(client, root, everything, fake_remote, db):
    await create(db, "extra")
    await create(db, "outer", type="group", group={"members": ["everything", "extra"]})
    await upload(client, root, OURS)
    await upload(client, root, "internal_tool-3.0.0.tar.gz", repository="extra")
    public_project(fake_remote, "requests", PUBLIC)

    ours = await client.get("/repository/outer/simple/internal-tool/", headers=root)
    theirs = await client.get("/repository/outer/simple/requests/", headers=root)
    fetched = await client.get(f"/repository/outer/packages/requests/2.31.0/{PUBLIC}", headers=root)

    assert names_on(ours) == [OURS, "internal_tool-3.0.0.tar.gz"]
    assert names_on(theirs) == [PUBLIC]
    assert fetched.content == content_of(PUBLIC)


async def test_a_metadata_file_comes_through_the_group(client, root, everything, fake_remote):
    metadata = b"Metadata-Version: 2.1\nName: requests\n"
    described = f'data-core-metadata="sha256={hashlib.sha256(metadata).hexdigest()}"'
    fake_remote.files["pypi/simple/requests/"] = remote_page(
        "requests", remote_link(PUBLIC, described)
    )
    fake_remote.files[f"packages/{PUBLIC}.metadata"] = metadata

    page = await client.get(f"{GROUP}/simple/requests/", headers=root)
    fetched = await client.get(f"{GROUP}/packages/requests/2.31.0/{PUBLIC}.metadata", headers=root)

    assert "data-core-metadata" in links(page)[0][0]
    assert (fetched.status_code, fetched.content) == (200, metadata)


async def test_reading_through_the_group_needs_read_on_the_group_only(
    client, root, everything, fake_remote, make_user, db
):
    await upload(client, root, OURS)
    public_project(fake_remote, "requests", PUBLIC)
    members = ["repository:pypi:pypi:read", "repository:pypi:upstream:read"]
    await roles.create_role(db, "group-readers", "", ["repository:pypi:everything:read"], [])
    await roles.create_role(db, "member-readers", "", members, [])
    await db.commit()
    await make_user("gina", roles=["group-readers"])
    await make_user("mel", roles=["member-readers"])
    gina, mel = basic("gina", PASSWORD), basic("mel", PASSWORD)

    ours = await client.get(f"{GROUP}/simple/internal-tool/", headers=gina)
    theirs = await client.get(f"{GROUP}/packages/requests/2.31.0/{PUBLIC}", headers=gina)
    refused = await client.get(f"{GROUP}/simple/internal-tool/", headers=mel)

    assert (names_on(ours), theirs.content) == ([OURS], content_of(PUBLIC))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_a_group_cannot_be_written_to(client, root, everything):
    data = content_of(OURS)
    body = form_body(upload_fields("internal-tool", "1.0.0", data), (OURS, data))
    await upload(client, root, OURS)

    uploaded = await client.post(
        f"{GROUP}/", content=body, headers={**root, "Content-Type": CONTENT_TYPE}
    )
    removed = await client.delete(f"{GROUP}/packages/internal-tool/1.0.0/{OURS}", headers=root)

    for response in (uploaded, removed):
        assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
        assert response.headers["Allow"] == "GET, HEAD"


async def test_the_root_index_lists_every_project_behind_the_group_once(
    client, root, everything, fake_remote
):
    await upload(client, root, OURS)
    await upload(client, root, "zope.interface-6.0.tar.gz")
    public_project(fake_remote, "requests", PUBLIC)
    public_project(fake_remote, "zope-interface", "zope.interface-5.0.tar.gz")
    await client.get(f"/repository/upstream/packages/requests/2.31.0/{PUBLIC}", headers=root)
    await client.get(
        "/repository/upstream/packages/zope-interface/5.0/zope.interface-5.0.tar.gz", headers=root
    )

    listed = await client.get(f"{GROUP}/simple/", headers=root)
    moved = await client.get(f"{GROUP}/simple", headers=root)

    assert links(listed) == [
        ({"href": "internal-tool/"}, "internal-tool"),
        ({"href": "requests/"}, "requests"),
        ({"href": "zope-interface/"}, "zope-interface"),
    ]
    assert (moved.status_code, moved.headers["Location"]) == (301, "simple/")
