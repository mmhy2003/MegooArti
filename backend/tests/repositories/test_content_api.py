"""The content API: what repositories hold, for the people who use them."""

import hashlib

import pytest

from megooarti.repositories import service
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code

CONTENT = "/api/v1/content"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


@pytest.fixture
async def reader(make_user, db) -> dict[str, str]:
    """May browse the repository `files`, and nothing else."""
    await roles.create_role(db, "browsers", "", ["repository:raw:files:browse"], [])
    await db.commit()
    await make_user("reader", roles=["browsers"])
    return basic("reader", PASSWORD)


async def put(client, headers, path: str, data: bytes | None = None, repository: str = "files"):
    sent = path.encode() if data is None else data
    response = await client.put(f"/repository/{repository}/{path}", content=sent, headers=headers)
    assert response.status_code == 201, response.text


async def create(db, name: str, **settings):
    made = await service.create_repository(
        db,
        name=name,
        format=settings.pop("format", "raw"),
        type=settings.pop("type", "hosted"),
        online=True,
        blob_store="default",
        **settings,
    )
    await db.commit()
    return made


async def test_the_repositories_a_caller_may_browse_are_listed(client, files, root, reader, db):
    await create(db, "private")
    await create(db, "mirror", type="proxy", proxy={"remote_url": "https://remote.test/files"})
    await create(db, "all", type="group", group={"members": ["files", "mirror"]})

    everything = await client.get(CONTENT, headers=root)
    some = await client.get(CONTENT, headers=reader)
    one = await client.get(f"{CONTENT}/files", headers=reader)
    hidden = await client.get(f"{CONTENT}/private", headers=reader)
    absent = await client.get(f"{CONTENT}/nothing", headers=reader)

    assert [item["name"] for item in everything.json()["items"]] == [
        "all",
        "files",
        "mirror",
        "private",
    ]
    assert everything.json()["total"] == 4
    group = everything.json()["items"][0]
    assert (group["type"], group["members"]) == ("group", ["files", "mirror"])
    assert some.json()["items"] == [one.json()]
    assert one.json() == {
        "name": "files",
        "format": "raw",
        "type": "hosted",
        "online": True,
        "url": "https://test/repository/files/",
        "members": None,
    }
    assert (hidden.status_code, error_code(hidden)) == (403, "forbidden")
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_the_list_is_paged(client, root, db):
    for name in ("a", "b", "c"):
        await create(db, name)

    page = await client.get(CONTENT, params={"limit": 2, "offset": 1}, headers=root)

    assert [item["name"] for item in page.json()["items"]] == ["b", "c"]
    assert (page.json()["total"], page.json()["limit"], page.json()["offset"]) == (3, 2, 1)


async def test_addresses_are_those_of_the_public_address(client, files, root, db):
    await set_setting(db, "base_url", "https://repo.example.com/")
    await db.commit()
    await put(client, root, "docs/guide.md")

    listed = await client.get(f"{CONTENT}/files", headers=root)
    detail = await client.get(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )

    assert listed.json()["url"] == "https://repo.example.com/repository/files/"
    assert detail.json()["download"] == "https://repo.example.com/repository/files/docs/guide.md"


async def test_a_folder_is_listed_with_its_files_and_folders(client, files, root):
    for path in ("readme.txt", "docs/guide.md", "docs/api/index.html"):
        await put(client, root, path)

    top = await client.get(f"{CONTENT}/files/tree", headers=root)
    docs = await client.get(f"{CONTENT}/files/tree", params={"path": "docs/"}, headers=root)

    assert [(item["kind"], item["name"]) for item in top.json()["items"]] == [
        ("folder", "docs"),
        ("file", "readme.txt"),
    ]
    assert top.json()["next"] is None
    folder, file = docs.json()["items"]
    assert folder == {
        "name": "api",
        "path": "docs/api",
        "kind": "folder",
        "size": None,
        "modified": None,
        "component": None,
    }
    assert (file["path"], file["size"]) == ("docs/guide.md", len(b"docs/guide.md"))
    assert file["component"]["name"] == "guide.md"


async def test_a_folder_is_read_page_by_page(client, files, root):
    for number in range(7):
        await put(client, root, f"logs/day-{number}.txt")

    first = await client.get(
        f"{CONTENT}/files/tree", params={"path": "logs", "limit": 3}, headers=root
    )
    names, following = [item["name"] for item in first.json()["items"]], first.json()["next"]
    while following:
        more = await client.get(
            f"{CONTENT}/files/tree",
            params={"path": "logs", "limit": 3, "after": following},
            headers=root,
        )
        names += [item["name"] for item in more.json()["items"]]
        following = more.json()["next"]

    assert names == [f"day-{number}.txt" for number in range(7)]


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"path": "nothing"}, 404, "not_found"),
        ({"path": "readme.txt"}, 404, "not_found"),  # a file is not a folder
        ({"path": "../etc"}, 400, "invalid_path"),
        ({"path": "a//b"}, 400, "invalid_path"),
        ({"after": "nonsense"}, 422, "validation_error"),
        ({"limit": 0}, 422, "validation_error"),
        ({"limit": 201}, 422, "validation_error"),
    ],
)
async def test_what_cannot_be_listed(client, files, root, params, status, code):
    await put(client, root, "readme.txt")

    response = await client.get(f"{CONTENT}/files/tree", params=params, headers=root)

    assert (response.status_code, error_code(response)) == (status, code)


async def test_an_empty_repository_has_an_empty_root(client, files, root):
    response = await client.get(f"{CONTENT}/files/tree", headers=root)

    assert response.json() == {"items": [], "next": None}


async def test_everything_about_a_file_is_told(client, files, root):
    data = b"the guide"
    await put(client, root, "docs/guide.md", data)
    await client.get("/repository/files/docs/guide.md", headers=root)

    response = await client.get(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )
    missing = await client.get(f"{CONTENT}/files/asset", params={"path": "docs"}, headers=root)
    unnamed = await client.get(f"{CONTENT}/files/asset", headers=root)

    detail = response.json()
    assert (detail["path"], detail["size"]) == ("docs/guide.md", len(data))
    assert detail["sha256"] == hashlib.sha256(data).hexdigest()
    assert detail["sha512"] == hashlib.sha512(data).hexdigest()
    assert detail["sha1"] == hashlib.sha1(data).hexdigest()
    assert detail["md5"] == hashlib.md5(data).hexdigest()
    assert (detail["blob_store"], detail["created_by"]) == ("default", "root")
    assert detail["created"] and detail["modified"] and detail["last_downloaded"]
    assert detail["last_verified"] is None  # only a proxy's file was ever verified
    assert detail["download"] == "https://test/repository/files/docs/guide.md"
    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert (unnamed.status_code, error_code(unnamed)) == (422, "validation_error")


async def test_the_components_of_a_repository_are_listed_and_opened(client, files, root):
    for path in ("docs/guide.md", "docs/intro.md", "readme.txt"):
        await put(client, root, path)

    listed = await client.get(f"{CONTENT}/files/components", headers=root)
    some = await client.get(
        f"{CONTENT}/files/components", params={"namespace": "docs"}, headers=root
    )
    one = await client.get(
        f"{CONTENT}/files/components",
        params={"namespace": "docs", "name": "intro.md"},
        headers=root,
    )
    opened = await client.get(
        f"{CONTENT}/files/components/{one.json()['items'][0]['id']}", headers=root
    )
    absent = await client.get(
        f"{CONTENT}/files/components/00000000-0000-0000-0000-000000000000", headers=root
    )

    assert listed.json()["total"] == 3
    assert [item["name"] for item in some.json()["items"]] == ["guide.md", "intro.md"]
    detail = opened.json()
    assert (detail["namespace"], detail["name"], detail["version"]) == ("docs", "intro.md", "")
    assert [file["path"] for file in detail["files"]] == ["docs/intro.md"]
    assert detail["created"] and detail["modified"]
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_a_component_is_found_only_in_its_own_repository(client, files, root, db):
    await create(db, "other")
    await put(client, root, "docs/guide.md")
    listed = await client.get(f"{CONTENT}/files/components", headers=root)

    elsewhere = await client.get(
        f"{CONTENT}/other/components/{listed.json()['items'][0]['id']}", headers=root
    )

    assert elsewhere.status_code == 404


async def test_a_group_lists_its_members_and_holds_nothing(client, files, root, db):
    await create(db, "all", type="group", group={"members": ["files"]})

    view = await client.get(f"{CONTENT}/all", headers=root)
    attempts = [
        await client.get(f"{CONTENT}/all/tree", headers=root),
        await client.get(f"{CONTENT}/all/asset", params={"path": "x"}, headers=root),
        await client.get(f"{CONTENT}/all/components", headers=root),
    ]

    assert view.json()["members"] == ["files"]
    for response in attempts:
        assert (response.status_code, error_code(response)) == (409, "not_browsable")


async def test_a_proxy_is_browsed_for_what_it_has_cached(client, mirror, fake_remote, root):
    fake_remote.files["files/lib/a.bin"] = b"from the remote"
    await client.get("/repository/mirror/lib/a.bin", headers=root)

    tree = await client.get(f"{CONTENT}/mirror/tree", params={"path": "lib"}, headers=root)
    detail = await client.get(f"{CONTENT}/mirror/asset", params={"path": "lib/a.bin"}, headers=root)

    assert [item["name"] for item in tree.json()["items"]] == ["a.bin"]
    assert detail.json()["created_by"] == "proxy"
    assert detail.json()["last_verified"] is not None


READS = [
    ("", {}),
    ("/files", {}),
    ("/files/tree", {}),
    ("/files/asset", {"path": "docs/guide.md"}),
    ("/files/components", {}),
]


@pytest.mark.parametrize(("path", "params"), READS)
async def test_seeing_needs_browse_and_nothing_else(
    client, files, root, reader, make_user, db, path, params
):
    await put(client, root, "docs/guide.md")
    await roles.create_role(db, "downloaders", "", ["repository:raw:files:read"], [])
    await db.commit()
    await make_user("downloader", roles=["downloaders"])
    downloader = basic("downloader", PASSWORD)

    allowed = await client.get(CONTENT + path, params=params, headers=reader)
    only_reads = await client.get(CONTENT + path, params=params, headers=downloader)
    nobody = await client.get(CONTENT + path, params=params)
    download = await client.get("/repository/files/docs/guide.md", headers=reader)

    assert allowed.status_code == 200
    if path:
        assert (only_reads.status_code, error_code(only_reads)) == (403, "forbidden")
    else:
        assert only_reads.json()["items"] == []  # the list leaves out what may not be browsed
    assert (nobody.status_code, error_code(nobody)) == (401, "unauthorized")
    assert download.status_code == 403  # browsing is not downloading


async def test_anyone_browses_what_the_anonymous_user_may(client, files, root, db):
    await create(db, "private")
    await put(client, root, "docs/guide.md")
    await roles.create_role(db, "public", "", ["repository:raw:files:browse"], [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    listed = await client.get(CONTENT)
    tree = await client.get(f"{CONTENT}/files/tree")
    hidden = await client.get(f"{CONTENT}/private/tree")

    assert [item["name"] for item in listed.json()["items"]] == ["files"]
    assert tree.status_code == 200
    assert hidden.status_code == 401  # nobody is signed in, so the answer is to sign in


async def test_someone_who_must_change_their_password_sees_nothing_yet(client, files, make_user):
    await make_user("fresh", roles=["admin"], must_change_password=True)

    response = await client.get(CONTENT, headers=basic("fresh", PASSWORD))

    assert (response.status_code, error_code(response)) == (403, "password_change_required")
