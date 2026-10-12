"""Uploading to a PyPI repository through the content API leaves it as twine would."""

import hashlib

import pytest

from tests.accounts import error_code
from tests.repositories.pypi.conftest import content_of, create, links, upload

UPLOAD = "/api/v1/content/pypi/upload"
WHEEL = "greeter-1.0-py3-none-any.whl"
SDIST = "greeter-1.0.tar.gz"


def parts(*filenames: str, field: str = "file") -> list:
    return [(field, (filename, content_of(filename))) for filename in filenames]


async def send(client, root, *filenames: str, to: str = UPLOAD, **fields):
    return await client.post(to, data=fields, files=parts(*filenames), headers=root)


async def test_uploaded_files_are_on_their_projects_page(client, index, root):
    response = await send(client, root, WHEEL, SDIST)
    page = await client.get("/repository/pypi/simple/greeter/", headers=root)
    wheel = await client.get(f"/repository/pypi/packages/greeter/1.0/{WHEEL}", headers=root)

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == [
        f"packages/greeter/1.0/{WHEEL}",
        f"packages/greeter/1.0/{SDIST}",
    ]
    assert [(c["namespace"], c["name"], c["version"]) for c in stored["components"]] == [
        ("", "greeter", "1.0")
    ]
    digest = hashlib.sha256(content_of(WHEEL)).hexdigest()
    assert [text for _, text in links(page)] == [WHEEL, SDIST]
    assert f"{WHEEL}#sha256={digest}" in page.text
    assert wheel.content == content_of(WHEEL)


async def test_a_project_is_kept_under_the_normal_form_of_its_name(client, index, root):
    response = await send(client, root, "My_Package-2.0-py3-none-any.whl", "my-package-2.0.zip")
    page = await client.get("/repository/pypi/simple/my-package/", headers=root)

    assert response.status_code == 201, response.text
    assert [file["path"] for file in response.json()["files"]] == [
        "packages/my-package/2.0/My_Package-2.0-py3-none-any.whl",
        "packages/my-package/2.0/my-package-2.0.zip",
    ]
    assert len(links(page)) == 2


async def test_what_the_form_says_of_the_files_is_kept_with_them(client, index, root):
    response = await send(
        client,
        root,
        WHEEL,
        summary="Says hello politely",
        requires_python=">=3.9",
        keywords="salutation,manners",
    )
    page = await client.get("/repository/pypi/simple/greeter/", headers=root)
    found = await client.get("/api/v1/search", params={"q": "politely manners"}, headers=root)

    assert response.status_code == 201, response.text
    assert links(page)[0][0]["data-requires-python"] == ">=3.9"
    assert [item["name"] for item in found.json()["items"]] == ["greeter"]


async def test_files_of_several_projects_can_come_together(client, index, root):
    response = await send(client, root, WHEEL, "other-0.3-py3-none-any.whl")

    assert response.status_code == 201, response.text
    assert sorted(found["name"] for found in response.json()["components"]) == ["greeter", "other"]


async def test_uploaded_and_twine_sent_files_are_one_project(client, index, root):
    assert (await upload(client, root, WHEEL)).status_code == 200

    response = await send(client, root, SDIST)
    page = await client.get("/repository/pypi/simple/greeter/", headers=root)

    assert response.status_code == 201, response.text
    assert [text for _, text in links(page)] == [WHEEL, SDIST]


@pytest.mark.parametrize(
    "filename",
    [
        "notes.txt",
        "greeter.tar.gz",
        "greeter-1.0.tar.bz2",
        "-1.0.tar.gz",
        "greeter-1.0-py3-none.whl",
        "gr$$ter-1.0.tar.gz",
        "greeter-1.0.egg",
    ],
)
async def test_a_file_whose_name_does_not_say_what_it_is_is_refused(client, index, root, filename):
    response = await send(client, root, WHEEL, filename)
    tree = await client.get("/api/v1/content/pypi/tree", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert filename in response.json()["error"]["message"]
    assert tree.json()["items"] == []  # the wheel that came with it did not stay


async def test_a_form_needs_files_and_nothing_it_does_not_know(client, index, root):
    two = await send(client, root, WHEEL, WHEEL)
    other = await client.post(UPLOAD, files=parts(WHEEL, field="content"), headers=root)
    misspelt = await send(client, root, WHEEL, sumary="Says hello")
    named = await send(client, root, WHEEL, name="greeter")

    for response in (two, other, misspelt, named):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
    fields = [r.json()["error"]["details"][0]["field"] for r in (two, other, misspelt, named)]
    assert fields == ["file", "content", "sumary", "name"]


async def test_what_the_form_says_must_be_fit_to_keep(client, index, root):
    response = await send(client, root, WHEEL, requires_python=">=3.9\x07")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")


async def test_an_upload_is_all_or_nothing_where_nothing_is_replaced(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    to = "/api/v1/content/once/upload"
    first = await send(client, root, WHEEL, to=to)

    again = await send(client, root, SDIST, WHEEL, to=to)
    page = await client.get("/repository/once/simple/greeter/", headers=root)

    assert first.status_code == 201, first.text
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert [text for _, text in links(page)] == [WHEEL]


async def found_by(client, root, words: str) -> list[str]:
    response = await client.get("/api/v1/search", params={"q": words}, headers=root)
    return [item["name"] for item in response.json()["items"]]


async def test_a_form_that_says_nothing_leaves_what_the_release_declares(client, index, root):
    sent = await upload(
        client, root, WHEEL, name="Greeter", summary="Says hello politely", keywords="manners"
    )
    assert sent.status_code == 200, sent.text

    response = await send(client, root, SDIST)

    assert response.status_code == 201, response.text
    assert await found_by(client, root, "politely") == ["greeter"]
    assert await found_by(client, root, "manners") == ["greeter"]


async def test_what_a_form_does_say_replaces_what_the_release_declared(client, index, root):
    await upload(client, root, WHEEL, summary="Says hello politely", keywords="manners")

    response = await send(client, root, SDIST, summary="Greets warmly")

    assert response.status_code == 201, response.text
    assert await found_by(client, root, "warmly") == ["greeter"]
    assert await found_by(client, root, "politely") == []
    assert await found_by(client, root, "manners") == ["greeter"]  # not said, so it stands
