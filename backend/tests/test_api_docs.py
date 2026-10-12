"""The API's documentation page asks nothing of another host (H6)."""

import re

import pytest

from megooarti.api_docs import ASSETS

DOCS = "/api/docs"


async def test_the_page_loads_its_script_and_its_stylesheet_from_this_server(client):
    response = await client.get(DOCS)
    page = response.text

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/html")
    loaded = re.findall(r"""(?:src|href)=["']([^"']+)["']""", page)
    assert sorted(loaded) == [
        "/api/docs/assets/favicon-32x32.png",
        "/api/docs/assets/swagger-ui-bundle.js",
        "/api/docs/assets/swagger-ui.css",
    ]
    # No address of another host anywhere in it: not a CDN, not a favicon.
    assert re.findall(r"""https?://[^\s"']+""", page) == []
    assert "/api/v1/openapi.json" in page
    # Swagger UI would ask swagger.io to validate the document of a server that is not
    # on localhost: it is told not to.
    assert '"validatorUrl": null' in page


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("swagger-ui-bundle.js", "text/javascript"),
        ("swagger-ui.css", "text/css"),
        ("favicon-32x32.png", "image/png"),
    ],
)
async def test_what_the_page_loads_is_served(client, name, kind):
    response = await client.get(f"{DOCS}/assets/{name}")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith(kind)
    assert response.content == (ASSETS / name).read_bytes()


@pytest.mark.parametrize("name", ["LICENSE", "VERSION", "nothing.js", "..%2Fnames.py"])
async def test_nothing_else_of_the_folder_is_served(client, name):
    response = await client.get(f"{DOCS}/assets/{name}")

    assert response.status_code == 404


def test_the_files_are_the_version_they_are_said_to_be_and_have_their_licence():
    version = (ASSETS / "VERSION").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"5\.\d+\.\d+", version)
    # The bundle says which Swagger UI it is.
    assert f'"{version}"'.encode() in (ASSETS / "swagger-ui-bundle.js").read_bytes()
    assert "Apache License" in (ASSETS / "LICENSE").read_text(encoding="utf-8")
    assert (ASSETS / "NOTICE").is_file()


async def test_the_api_document_is_where_the_page_says(client):
    document = (await client.get("/api/v1/openapi.json")).json()

    assert document["info"]["title"] == "MegooArti"
    # The page and its files are not operations of the API.
    assert not [path for path in document["paths"] if path.startswith(DOCS)]
