import hashlib
from html.parser import HTMLParser

import pytest
from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.pypi.conftest import (
    CONTENT_TYPE,
    SDIST,
    URL,
    WHEEL,
    content_of,
    create,
    form_body,
    upload,
    upload_fields,
)

PAGE = f"{URL}/simple/megooarti-greeter/"
FILES = f"{URL}/packages/megooarti-greeter/1.0.0"


class Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[dict, str]] = []
        self._open: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open = dict(attrs)

    def handle_data(self, data):
        if self._open is not None:
            self.found.append((self._open, data))
            self._open = None


def links(response) -> list[tuple[dict, str]]:
    parser = Anchors()
    parser.feed(response.text)
    return parser.found


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def left_in_storage(settings) -> list[str]:
    """The files the blob store holds, temporary ones included."""
    store = settings.data_dir / "blobs" / "default"
    return [path.name for path in store.rglob("*") if path.is_file()] if store.exists() else []


async def test_an_uploaded_file_can_be_downloaded(client, index, root, db):
    uploaded = await upload(client, root, WHEEL, summary="Says hello", requires_python=">=3.9")

    fetched = await client.get(f"{FILES}/{WHEEL}", headers=root)
    part = await client.get(f"{FILES}/{WHEEL}", headers={**root, "Range": "bytes=0-3"})

    data = content_of(WHEEL)
    assert (uploaded.status_code, uploaded.content) == (200, b""), uploaded.text
    assert (fetched.status_code, fetched.content) == (200, data)
    assert fetched.headers["Content-Type"] == "application/octet-stream"
    assert fetched.headers["ETag"] == f'"{hashlib.sha256(data).hexdigest()}"'
    assert fetched.headers["Content-Disposition"].startswith(f'attachment; filename="{WHEEL}"')
    assert (part.status_code, part.content) == (206, data[:4])
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == (
        "",
        "megooarti-greeter",
        "1.0.0",
    )
    assert component.attributes == {
        "pypi": {"name": "megooarti_greeter", "version": "1.0.0", "summary": "Says hello"}
    }
    asset = await db.scalar(select(Asset))
    assert asset.path == f"packages/megooarti-greeter/1.0.0/{WHEEL}"
    assert asset.attributes == {"pypi": {"requires_python": ">=3.9"}}


async def test_the_project_page_lists_what_is_stored(client, index, root):
    await upload(client, root, WHEEL, requires_python=">=3.9")
    await upload(client, root, SDIST)
    await upload(client, root, "megooarti_greeter-1.1.0.tar.gz")
    await upload(client, root, "unrelated-9.0.tar.gz")

    page = await client.get(PAGE, headers=root)

    assert page.status_code == 200, page.text
    assert page.headers["Content-Type"] == "text/html; charset=utf-8"
    assert page.headers["Content-Security-Policy"] == "sandbox"
    assert page.headers["X-Content-Type-Options"] == "nosniff"

    def link(version: str, filename: str, **attributes) -> tuple[dict, str]:
        digest = hashlib.sha256(content_of(filename)).hexdigest()
        href = f"../../packages/megooarti-greeter/{version}/{filename}#sha256={digest}"
        return {"href": href, **attributes}, filename

    assert links(page) == [
        link("1.0.0", WHEEL, **{"data-requires-python": ">=3.9"}),
        link("1.0.0", SDIST),
        link("1.1.0", "megooarti_greeter-1.1.0.tar.gz"),
    ]


async def test_a_link_on_the_page_leads_to_the_file(client, index, root):
    await upload(client, root, WHEEL)
    page = await client.get(PAGE, headers=root)
    href = links(page)[0][0]["href"]

    fetched = await client.get(str(page.url.join(href)), headers=root)

    assert (fetched.status_code, fetched.content) == (200, content_of(WHEEL))


async def test_the_page_is_answered_like_any_content(client, index, root):
    await upload(client, root, WHEEL)
    first = await client.get(PAGE, headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(PAGE, headers={**root, "If-None-Match": etag})
    headed = await client.head(PAGE, headers=root)
    await upload(client, root, SDIST)
    changed = await client.get(PAGE, headers={**root, "If-None-Match": etag})

    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (headed.status_code, headed.content, headed.headers["ETag"]) == (200, b"", etag)
    assert (changed.status_code, len(links(changed))) == (200, 2)


async def test_every_spelling_of_a_name_is_one_project(client, index, root, db):
    await upload(client, root, WHEEL, name="Megooarti_Greeter")
    await upload(client, root, SDIST, name="megooarti.greeter")

    page = await client.get(PAGE, headers=root)

    assert [text for _, text in links(page)] == [WHEEL, SDIST]
    assert await count(db, Component) == 1


@pytest.mark.parametrize(
    ("asked", "location"),
    [
        ("simple", "simple/"),
        ("simple/megooarti-greeter", "megooarti-greeter/"),
        ("simple/Megooarti_Greeter", "megooarti-greeter/"),
        ("simple/Megooarti_Greeter/", "../megooarti-greeter/"),
        ("simple/megooarti.greeter/", "../megooarti-greeter/"),
    ],
)
async def test_a_page_has_one_address_and_the_others_lead_to_it(
    client, index, root, asked, location
):
    await upload(client, root, WHEEL)

    moved = await client.get(f"{URL}/{asked}", headers=root)
    followed = await client.get(f"{URL}/{asked}", headers=root, follow_redirects=True)

    assert (moved.status_code, moved.headers["Location"]) == (301, location)
    assert followed.status_code == 200
    assert followed.url.path in (f"{URL}/simple/", f"{URL}/simple/megooarti-greeter/")


async def test_the_root_index_lists_the_projects_held(client, index, root):
    empty = await client.get(f"{URL}/simple/", headers=root)
    await upload(client, root, "zope.interface-6.0.tar.gz")
    await upload(client, root, WHEEL)
    await upload(client, root, SDIST)

    listed = await client.get(f"{URL}/simple/", headers=root)

    assert (empty.status_code, links(empty)) == (200, [])
    assert links(listed) == [
        ({"href": "megooarti-greeter/"}, "megooarti-greeter"),
        ({"href": "zope-interface/"}, "zope-interface"),
    ]
    assert listed.headers["Content-Type"] == "text/html; charset=utf-8"


async def test_a_deleted_file_leaves_the_page_and_the_last_one_takes_the_project(
    client, index, root, db
):
    await upload(client, root, WHEEL)
    await upload(client, root, SDIST)

    removed = await client.delete(f"{FILES}/{WHEEL}", headers=root)
    after_one = await client.get(PAGE, headers=root)
    again = await client.delete(f"{FILES}/{WHEEL}", headers=root)
    await client.delete(f"{FILES}/{SDIST}", headers=root)
    after_all = await client.get(PAGE, headers=root)

    assert removed.status_code == 204
    assert [text for _, text in links(after_one)] == [SDIST]
    assert (again.status_code, error_code(again)) == (404, "not_found")
    assert (after_all.status_code, error_code(after_all)) == (404, "not_found")
    assert await count(db, Component) == 0


async def test_a_project_nobody_uploaded_is_not_found(client, index, root):
    response = await client.get(f"{URL}/simple/requests/", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


@pytest.mark.parametrize("field", ["sha256_digest", "md5_digest"])
async def test_a_file_that_is_not_the_one_declared_is_refused(
    client, index, root, db, settings, field
):
    wrong = hashlib.new(field.partition("_")[0], b"another file").hexdigest()

    response = await upload(client, root, WHEEL, **{field: wrong})

    assert (response.status_code, error_code(response)) == (400, "checksum_mismatch")
    assert await count(db, Asset) == 0
    assert left_in_storage(settings) == []


async def test_a_digest_the_store_does_not_compute_is_not_checked(client, index, root):
    response = await upload(client, root, WHEEL, blake2_256_digest="0" * 64)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {":action": "submit"},
        {":action": None},
        {"name": "-not-a-name-"},
        {"name": "another-project"},
        {"version": "../.."},
        {"version": None},
        {"sha256_digest": "not hex"},
        {"requires_python": ">=3.9\n<4"},
    ],
    ids=lambda changes: next(iter(changes)) + "=" + str(next(iter(changes.values())))[:12],
)
async def test_an_upload_that_is_not_acceptable_stores_nothing(
    client, index, root, db, settings, changes
):
    response = await upload(client, root, WHEEL, **changes)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert await count(db, Asset) == 0
    assert left_in_storage(settings) == []


@pytest.mark.parametrize(
    "filename",
    ["megooarti_greeter-1.0.0.exe", "megooarti_greeter-1.0.0-py3-none.whl", "x y-1.0.0.tar.gz"],
)
async def test_a_file_of_a_kind_that_is_not_taken_is_refused(
    client, index, root, db, settings, filename
):
    response = await upload(client, root, filename, name="megooarti-greeter", version="1.0.0")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert left_in_storage(settings) == []


async def test_a_body_that_is_not_an_upload_form_is_refused(client, index, root, db, settings):
    data = content_of(WHEEL)
    whole = form_body(upload_fields("megooarti-greeter", "1.0.0", data), (WHEEL, data))
    no_file = form_body(upload_fields("megooarti-greeter", "1.0.0", data), None)
    two_files = form_body(
        upload_fields("megooarti-greeter", "1.0.0", data),
        (WHEEL, data),
        extra=[("content", (SDIST, b"another"))],
    )
    form = {**root, "Content-Type": CONTENT_TYPE}
    sent = [
        await client.post(f"{URL}/", json={"name": "megooarti-greeter"}, headers=root),
        await client.post(f"{URL}/", content=whole, headers=root),  # no content type
        await client.post(f"{URL}/", content=whole[: len(whole) // 2], headers=form),
        await client.post(f"{URL}/", content=b"", headers=form),
        await client.post(f"{URL}/", content=no_file, headers=form),
        await client.post(f"{URL}/", content=two_files, headers=form),
    ]

    for response in sent:
        assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert await count(db, Asset) == 0
    assert left_in_storage(settings) == []


async def test_a_large_file_arrives_whole(client, index, root):
    data = bytes(range(256)) * 4096 * 5  # 5 MiB, sent in many pieces
    body = form_body(upload_fields("megooarti-greeter", "1.0.0", data), (WHEEL, data))

    async def pieces():
        for start in range(0, len(body), 65_521):
            yield body[start : start + 65_521]

    uploaded = await client.post(
        f"{URL}/", content=pieces(), headers={**root, "Content-Type": CONTENT_TYPE}
    )
    fetched = await client.get(f"{FILES}/{WHEEL}", headers=root)

    assert uploaded.status_code == 200, uploaded.text
    assert hashlib.sha256(fetched.content).hexdigest() == hashlib.sha256(data).hexdigest()


async def test_uploading_a_file_again_replaces_it_unless_the_policy_forbids(client, db, root):
    await create(db, "pypi")
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    for repository in ("pypi", "once"):
        await upload(client, root, WHEEL, repository=repository, summary="first")

    replaced = await upload(client, root, WHEEL, data=b"rebuilt", summary="second")
    refused = await upload(client, root, WHEEL, repository="once", data=b"rebuilt")
    another = await upload(client, root, SDIST, repository="once", summary="third")
    page = await client.get(PAGE, headers=root)
    kept = await client.get(
        f"/repository/once/packages/megooarti-greeter/1.0.0/{WHEEL}", headers=root
    )

    assert replaced.status_code == 200
    assert links(page)[0][0]["href"].endswith(f"#sha256={hashlib.sha256(b'rebuilt').hexdigest()}")
    kept_about = [
        held["pypi"]["summary"] for held in await db.scalars(select(Component.attributes))
    ]
    assert sorted(kept_about) == ["second", "third"]  # the release's, from the last upload
    assert (refused.status_code, error_code(refused)) == (409, "redeploy_disabled")
    assert another.status_code == 200  # a new file of the same version is not a redeploy
    assert kept.content == content_of(WHEEL)


async def test_a_file_name_has_one_address_whatever_version_is_declared(
    client, db, root, make_user
):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    permissions = ["repository:pypi:once:add", "repository:pypi:once:read"]
    await roles.create_role(db, "adders", "", permissions, [])
    await db.commit()
    await make_user("adder", roles=["adders"])
    adder = basic("adder", PASSWORD)
    first = await upload(client, root, SDIST, repository="once", version="1.0.0.0")

    # The same file name again, said to belong to other versions.
    by_policy = await upload(client, root, SDIST, repository="once", data=b"rebuilt", version="9")
    by_adder = await upload(client, adder, SDIST, repository="once", data=b"rebuilt", version="0")
    page = await client.get("/repository/once/simple/megooarti-greeter/", headers=root)

    assert first.status_code == 200
    assert (by_policy.status_code, error_code(by_policy)) == (409, "redeploy_disabled")
    assert (by_adder.status_code, error_code(by_adder)) == (403, "forbidden")
    digest = hashlib.sha256(content_of(SDIST)).hexdigest()
    assert links(page) == [
        ({"href": f"../../packages/megooarti-greeter/1.0.0/{SDIST}#sha256={digest}"}, SDIST)
    ]
    component = await db.scalar(select(Component))
    # The address has the version in the file's name; what was declared is kept beside it.
    assert (component.version, component.attributes["pypi"]["version"]) == ("1.0.0", "1.0.0.0")


async def test_a_read_only_repository_refuses_before_reading_the_file(client, db, root, settings):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await upload(client, root, WHEEL, repository="frozen")

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")
    assert left_in_storage(settings) == []


async def test_each_change_needs_its_own_permission(client, index, root, make_user, db):
    for action in ("read", "add", "edit", "delete"):
        permissions = [f"repository:pypi:pypi:{action}"]
        await roles.create_role(db, f"only-{action}", "", permissions, [])
    await db.commit()
    for action in ("read", "add", "edit", "delete"):
        await make_user(f"{action}er", roles=[f"only-{action}"])
    reader, adder, editor, deleter = (
        basic(f"{action}er", PASSWORD) for action in ("read", "add", "edit", "delete")
    )

    by_reader = await upload(client, reader, WHEEL)
    by_deleter = await upload(client, deleter, WHEEL)
    by_adder = await upload(client, adder, WHEEL)
    adder_again = await upload(client, adder, WHEEL, data=b"rebuilt")
    by_editor = await upload(client, editor, WHEEL, data=b"rebuilt")
    editor_new = await upload(client, editor, SDIST)
    page = await client.get(PAGE, headers=reader)
    unreadable = await client.get(PAGE, headers=adder)
    not_deleted = await client.delete(f"{FILES}/{WHEEL}", headers=editor)
    deleted = await client.delete(f"{FILES}/{WHEEL}", headers=deleter)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert (by_deleter.status_code, error_code(by_deleter)) == (403, "forbidden")
    assert by_adder.status_code == 200
    assert (adder_again.status_code, error_code(adder_again)) == (403, "forbidden")
    assert by_editor.status_code == 200
    assert (editor_new.status_code, error_code(editor_new)) == (403, "forbidden")
    assert page.status_code == 200
    assert (unreadable.status_code, error_code(unreadable)) == (403, "forbidden")
    assert (not_deleted.status_code, error_code(not_deleted)) == (403, "forbidden")
    assert deleted.status_code == 204


async def test_without_credentials_there_is_a_basic_challenge(client, index):
    data = content_of(WHEEL)
    body = form_body(upload_fields("megooarti-greeter", "1.0.0", data), (WHEEL, data))

    uploaded = await client.post(f"{URL}/", content=body, headers={"Content-Type": CONTENT_TYPE})
    page = await client.get(PAGE)

    for response in (uploaded, page):
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
        assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_a_token_is_accepted_the_way_python_tools_send_it(
    client, index, make_user, make_token
):
    owner = await make_user("dana", roles=["admin"])
    token = await make_token(owner)

    uploaded = await upload(client, basic("__token__", token), WHEEL)
    page = await client.get(PAGE, headers=basic("__token__", token))
    refused = await upload(client, basic("__token__", PASSWORD), SDIST)

    assert (uploaded.status_code, page.status_code) == (200, 200)
    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


@pytest.mark.parametrize(
    ("method", "path", "status", "allow"),
    [
        ("GET", "", 405, "POST"),
        ("PUT", "", 405, "POST"),
        ("DELETE", "", 405, "POST"),
        ("POST", "simple/", 405, "GET, HEAD"),
        ("DELETE", "simple/megooarti-greeter/", 405, "GET, HEAD"),
        ("PUT", f"packages/megooarti-greeter/1.0.0/{WHEEL}", 405, "GET, HEAD, DELETE"),
        ("POST", f"packages/megooarti-greeter/1.0.0/{WHEEL}", 405, "GET, HEAD, DELETE"),
        ("GET", f"packages/megooarti-greeter/1.0.0/{WHEEL}.metadata", 404, None),
        ("GET", "pypi/megooarti-greeter/json", 404, None),
        ("GET", "simple/megooarti-greeter/index.html", 404, None),
        ("GET", "packages/Megooarti_Greeter/1.0.0/x.whl", 404, None),
        ("POST", "legacy/", 404, None),
    ],
)
async def test_what_an_address_does_not_do(client, index, root, method, path, status, allow):
    await upload(client, root, WHEEL)

    response = await client.request(method, f"{URL}/{path}", headers=root)

    assert response.status_code == status
    assert error_code(response) == ("method_not_allowed" if status == 405 else "not_found")
    assert response.headers.get("Allow") == allow


async def test_what_a_file_declares_cannot_break_the_page(client, index, root):
    hostile = '">3"><script>alert(1)</script>'
    await upload(client, root, WHEEL, requires_python=hostile)

    page = await client.get(PAGE, headers=root)

    assert "<script>" not in page.text
    assert links(page)[0][0]["data-requires-python"] == hostile
