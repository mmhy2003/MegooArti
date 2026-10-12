"""Uploading through the content API: the route, and what the generic format takes."""

import hashlib

import pytest

from megooarti.repositories import forms, service
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.test_forms import TYPE, form_of, part

UPLOAD = "/api/v1/content/files/upload"
BIG = bytes(range(256)) * 12_000  # about 3 MiB: more than one piece of a body


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


def temporary_files(settings) -> list:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


def parts(*files: tuple[str, bytes], field: str = "file") -> list:
    return [(field, (name, data)) for name, data in files]


async def someone_who_may(db, make_user, *actions: str) -> dict[str, str]:
    """Somebody who may do exactly these things to the repository `files`."""
    may = [f"repository:raw:files:{action}" for action in actions]
    await roles.create_role(db, "some", "", may, [])
    await db.commit()
    await make_user("someone", roles=["some"])
    return basic("someone", PASSWORD)


async def held(client, headers, repository: str = "files") -> list[str]:
    """Every file a repository holds, by walking its tree."""
    found, folders = [], [""]
    while folders:
        response = await client.get(
            f"/api/v1/content/{repository}/tree",
            params={"path": folders.pop(), "limit": 200},
            headers=headers,
        )
        for item in response.json().get("items", []):
            (folders if item["kind"] == "folder" else found).append(item["path"])
    return sorted(found)


async def test_files_are_stored_under_a_directory_by_their_names(client, files, root):
    response = await client.post(
        UPLOAD,
        data={"directory": "docs/v1"},
        files=parts(("guide.md", b"# Guide"), ("logo.png", b"\x89PNG")),
        headers=root,
    )
    guide = await client.get("/repository/files/docs/v1/guide.md", headers=root)
    logo = await client.get("/repository/files/docs/v1/logo.png", headers=root)

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == ["docs/v1/guide.md", "docs/v1/logo.png"]
    assert stored["files"][0]["sha256"] == hashlib.sha256(b"# Guide").hexdigest()
    assert stored["files"][0]["created_by"] == "root"
    assert stored["files"][0]["download"].endswith("/repository/files/docs/v1/guide.md")
    assert [(found["namespace"], found["name"]) for found in stored["components"]] == [
        ("docs/v1", "guide.md"),
        ("docs/v1", "logo.png"),
    ]
    assert stored["files"][1]["component"] == stored["components"][1]
    assert (guide.content, logo.content) == (b"# Guide", b"\x89PNG")
    assert logo.headers["Content-Type"] == "image/png"  # by its name, as for any file


@pytest.mark.parametrize("directory", [None, "", "/"])
async def test_without_a_directory_a_file_goes_to_the_root(client, files, root, directory):
    data = {} if directory is None else {"directory": directory}

    response = await client.post(
        UPLOAD, data=data, files=parts(("notes.txt", b"notes")), headers=root
    )

    assert response.status_code == 201, response.text
    assert await held(client, root) == ["notes.txt"]


async def test_a_directory_is_taken_with_or_without_slashes_around_it(client, files, root):
    response = await client.post(
        UPLOAD, data={"directory": "/a/b/"}, files=parts(("c.txt", b"c")), headers=root
    )

    assert response.status_code == 201, response.text
    assert await held(client, root) == ["a/b/c.txt"]


async def test_a_large_file_arrives_whole(client, files, root, settings):
    response = await client.post(
        UPLOAD, data={"directory": "big"}, files=parts(("data.bin", BIG)), headers=root
    )
    fetched = await client.get("/repository/files/big/data.bin", headers=root)

    assert response.status_code == 201, response.text
    assert response.json()["files"][0]["size"] == len(BIG)
    assert fetched.content == BIG
    assert temporary_files(settings) == []


async def test_uploading_again_replaces_the_file(client, files, root):
    for content in (b"first", b"second"):
        response = await client.post(UPLOAD, files=parts(("a.txt", content)), headers=root)
        assert response.status_code == 201, response.text

    fetched = await client.get("/repository/files/a.txt", headers=root)

    assert fetched.content == b"second"


@pytest.mark.parametrize(
    ("data", "sent", "field"),
    [
        ({}, parts(("a/b.txt", b"x")), "file"),
        ({}, parts(("a\\b.txt", b"x")), "file"),
        ({}, parts(("a.txt", b"x"), ("a.txt", b"y")), "file"),
        ({}, parts(("a.txt", b"x"), field="upload"), "upload"),
        ({"directroy": "docs"}, parts(("a.txt", b"x")), "directroy"),
    ],
    ids=["slash", "backslash", "twice", "other-part", "misspelt"],
)
async def test_a_form_that_lacks_what_is_needed_is_refused_and_says_where(
    client, files, root, settings, data, sent, field
):
    response = await client.post(UPLOAD, data=data, files=sent, headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert [detail["field"] for detail in response.json()["error"]["details"]] == [field]
    assert await held(client, root) == []
    assert temporary_files(settings) == []


@pytest.mark.parametrize(
    "directory", ["a/../b", "a//b", "..", "a\\b", "x" * 1100], ids=["up", "empty", "dots", "b", "l"]
)
async def test_a_directory_must_be_a_path_a_repository_can_hold(
    client, files, root, settings, directory
):
    response = await client.post(
        UPLOAD, data={"directory": directory}, files=parts(("a.txt", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert temporary_files(settings) == []


@pytest.mark.parametrize("name", ["..", "."])
async def test_a_file_cannot_be_named_as_a_way_out_of_its_directory(client, files, root, name):
    response = await client.post(
        UPLOAD, data={"directory": "docs"}, files=parts((name, b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert await held(client, root) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (form_of(part("directory", "docs")), "At least one file"),
        # A file input of a page that nobody filled in.
        (form_of(part("directory", "docs"), part("file", b"", "")), "At least one file"),
        # `-F file=text` where `-F file=@path` was meant.
        (form_of(part("file", "the content")), "sent as one, with a file name"),
    ],
    ids=["none", "unfilled", "as-text"],
)
async def test_a_form_without_a_file_is_refused(client, files, root, body, said):
    response = await client.post(UPLOAD, content=body, headers={**root, "Content-Type": TYPE})

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    details = response.json()["error"]["details"]
    assert [detail["field"] for detail in details] == ["file"]
    assert said in details[0]["message"]
    assert await held(client, root) == []


async def test_what_is_not_a_form_is_refused(client, files, root):
    as_json = await client.post(UPLOAD, json={"directory": "docs"}, headers=root)
    cut_short = await client.post(
        UPLOAD,
        content=b'--x\r\nContent-Disposition: form-data; name="file"; filename="a"\r\n\r\nabc',
        headers={**root, "Content-Type": "multipart/form-data; boundary=x"},
    )

    for response in (as_json, cut_short):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert "not a multipart form" in as_json.json()["error"]["message"]
    assert "cut short" in cut_short.json()["error"]["message"]


async def test_an_upload_is_all_or_nothing(client, root, db, settings):
    await service.create_repository(
        db,
        name="once",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": "disable_redeploy"},
        format_config={},
    )
    await db.commit()
    address = "/api/v1/content/once/upload"
    first = await client.post(address, files=parts(("b.txt", b"held")), headers=root)

    second = await client.post(
        address,
        files=parts(("a.txt", b"new"), ("b.txt", b"other"), ("c.txt", b"new")),
        headers=root,
    )
    kept = await client.get("/repository/once/b.txt", headers=root)

    assert first.status_code == 201, first.text
    assert (second.status_code, error_code(second)) == (409, "redeploy_disabled")
    assert await held(client, root, "once") == ["b.txt"]  # a.txt did not stay behind
    assert kept.content == b"held"
    assert temporary_files(settings) == []


async def test_adding_needs_add_and_replacing_needs_edit(client, files, db, make_user, root):
    adder = await someone_who_may(db, make_user, "add")

    added = await client.post(UPLOAD, files=parts(("a.txt", b"one")), headers=adder)
    replaced = await client.post(UPLOAD, files=parts(("a.txt", b"two")), headers=adder)
    fetched = await client.get("/repository/files/a.txt", headers=root)

    assert added.status_code == 201, added.text
    assert added.json()["files"][0]["path"] == "a.txt"  # with no right to browse or to read
    assert (replaced.status_code, error_code(replaced)) == (403, "forbidden")
    assert fetched.content == b"one"


async def test_edit_alone_replaces_and_does_not_add(client, files, db, make_user, root):
    await client.post(UPLOAD, files=parts(("a.txt", b"one")), headers=root)
    editor = await someone_who_may(db, make_user, "edit")

    replaced = await client.post(UPLOAD, files=parts(("a.txt", b"two")), headers=editor)
    added = await client.post(UPLOAD, files=parts(("b.txt", b"new")), headers=editor)

    assert replaced.status_code == 201, replaced.text
    assert (added.status_code, error_code(added)) == (403, "forbidden")
    assert await held(client, root) == ["a.txt"]


async def test_reading_and_browsing_are_not_uploading(client, files, db, make_user, settings):
    reader = await someone_who_may(db, make_user, "browse", "read", "delete")

    refused = await client.post(UPLOAD, files=parts(("a.txt", BIG)), headers=reader)
    nobody = await client.post(UPLOAD, files=parts(("a.txt", b"x")))

    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert nobody.status_code == 401
    assert temporary_files(settings) == []


async def test_a_visitor_who_may_add_is_asked_to_sign_in_the_way_the_api_asks(
    client, files, db, root
):
    await client.post(UPLOAD, files=parts(("a.txt", b"held")), headers=root)
    await roles.create_role(db, "drop", "", ["repository:raw:files:add"], [])
    await db.commit()
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["drop"])
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    added = await client.post(UPLOAD, files=parts(("b.txt", b"new")))
    replaced = await client.post(UPLOAD, files=parts(("a.txt", b"other")))

    assert added.status_code == 201, added.text
    assert replaced.status_code == 401
    # Not `Basic`, which a browser answers with a dialog of its own.
    assert replaced.headers["WWW-Authenticate"].startswith("Bearer")


async def test_a_read_only_repository_refuses_before_anything_is_read(client, root, db, settings):
    await service.create_repository(
        db,
        name="frozen",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": "read_only"},
        format_config={},
    )
    await db.commit()

    response = await client.post(
        "/api/v1/content/frozen/upload", files=parts(("a.txt", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")
    assert temporary_files(settings) == []


async def test_an_offline_repository_is_still_filled_by_whoever_tends_it(client, files, root, db):
    files.online = False
    await db.commit()

    response = await client.post(UPLOAD, files=parts(("a.txt", b"x")), headers=root)
    by_client = await client.put("/repository/files/b.txt", content=b"x", headers=root)

    assert response.status_code == 201, response.text
    assert (by_client.status_code, error_code(by_client)) == (503, "repository_offline")


async def test_only_a_hosted_repository_takes_an_upload(client, files, mirror, root, db):
    await service.create_repository(
        db,
        name="all",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    await db.commit()

    proxy = await client.post(
        "/api/v1/content/mirror/upload", files=parts(("a.txt", b"x")), headers=root
    )
    group = await client.post(
        "/api/v1/content/all/upload", files=parts(("a.txt", b"x")), headers=root
    )

    for response in (proxy, group):
        assert (response.status_code, error_code(response)) == (409, "upload_not_supported")
    assert "hosted" in proxy.json()["error"]["message"]
    assert await held(client, root) == []


async def test_an_image_is_not_uploaded(client, root, db):
    await service.create_repository(
        db,
        name="images",
        format="docker",
        type="hosted",
        online=True,
        blob_store="default",
        format_config={},
    )
    await db.commit()

    response = await client.post(
        "/api/v1/content/images/upload", files=parts(("image.tar", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (409, "upload_not_supported")
    assert "container client" in response.json()["error"]["message"]


async def test_there_is_no_uploading_to_a_repository_that_is_not_there(client, root):
    response = await client.post(
        "/api/v1/content/nowhere/upload", files=parts(("a.txt", b"x")), headers=root
    )

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_no_database_connection_is_held_while_the_form_arrives(
    client, files, root, db, monkeypatch
):
    in_transaction = []
    read = forms.read

    async def watched(*arguments, **named):
        in_transaction.append(db.in_transaction())
        return await read(*arguments, **named)

    monkeypatch.setattr(forms, "read", watched)

    response = await client.post(UPLOAD, files=parts(("a.txt", b"x")), headers=root)

    assert response.status_code == 201, response.text
    assert in_transaction == [False]


async def test_the_api_document_says_an_upload_is_a_form(client):
    document = (await client.get("/api/v1/openapi.json")).json()

    described = document["paths"]["/api/v1/content/{repository}/upload"]["post"]

    assert list(described["requestBody"]["content"]) == ["multipart/form-data"]
    assert described["requestBody"]["required"] is True
    assert "201" in described["responses"]


def content_files(settings) -> list[str]:
    """What the blob store holds for good, by the names of the files: their hashes."""
    directory = settings.data_dir / "blobs" / "default" / "content"
    return sorted(path.name for path in directory.rglob("*") if path.is_file())


async def test_a_refused_form_leaves_none_of_its_files_in_the_blob_store(
    client, files, root, db, settings
):
    await service.create_repository(
        db,
        name="once",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": "disable_redeploy"},
        format_config={},
    )
    await db.commit()
    await client.post("/api/v1/content/once/upload", files=parts(("b.txt", b"held")), headers=root)
    await client.post(UPLOAD, files=parts(("elsewhere.txt", b"shared")), headers=root)
    before = content_files(settings)

    refused = await client.post(
        "/api/v1/content/once/upload",
        files=parts(("a.bin", BIG), ("same.txt", b"shared"), ("b.txt", b"other")),
        headers=root,
    )
    elsewhere = await client.get("/repository/files/elsewhere.txt", headers=root)

    assert (refused.status_code, error_code(refused)) == (409, "redeploy_disabled")
    assert before == sorted(hashlib.sha256(data).hexdigest() for data in (b"held", b"shared"))
    # Not the megabytes of a.bin, which no record knows of. And what another repository
    # holds is still there, though the refused form carried the same content.
    assert content_files(settings) == before
    assert elsewhere.content == b"shared"
