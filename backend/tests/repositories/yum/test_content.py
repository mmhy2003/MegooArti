"""A YUM repository through the content API: upload, components, search and usage."""

import gzip
import re

from tests.accounts import error_code
from tests.repositories.yum.conftest import URL, create, upload
from tests.repositories.yum.packages import DATA, HELLO, TOOL, make_rpm

UPLOAD = "/api/v1/content/yum-hosted/upload"
COMPONENTS = "/api/v1/content/yum-hosted/components"


def parts(*packages: tuple[str, bytes], field: str = "file") -> list:
    return [(field, package) for package in packages]


async def primary(client, headers, directory: str = "") -> str:
    base = f"{URL}/{directory}/repodata" if directory else f"{URL}/repodata"
    repomd = (await client.get(f"{base}/repomd.xml", headers=headers)).text
    href = re.search(r'href="repodata/([^"]+-primary\.xml\.gz)"', repomd)[1]
    return gzip.decompress((await client.get(f"{base}/{href}", headers=headers)).content).decode()


async def test_packages_uploaded_in_a_form_are_kept_in_its_directory(client, db, root):
    await create(db, format_config={"repodata_depth": 2})
    hello = (HELLO, (DATA / HELLO).read_bytes())
    tool = (TOOL, (DATA / TOOL).read_bytes())

    response = await client.post(
        UPLOAD, data={"directory": "/el9/x86_64/"}, files=parts(hello, tool), headers=root
    )
    listed = await primary(client, root, "el9/x86_64")

    assert response.status_code == 201, response.text
    assert [file["path"] for file in response.json()["files"]] == [
        f"el9/x86_64/{HELLO}",
        f"el9/x86_64/{TOOL}",
    ]
    assert 'packages="2"' in listed


async def test_a_form_with_a_file_that_is_not_a_package_stores_none_of_them(client, hosted, root):
    response = await client.post(
        UPLOAD, files=parts(("a.rpm", make_rpm()), ("b.rpm", b"not an rpm")), headers=root
    )

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert 'packages="0"' in await primary(client, root)


async def test_a_form_that_cannot_be_kept_as_it_is_is_refused(client, db, root):
    await create(db, format_config={"repodata_depth": 1})

    twice = await client.post(
        UPLOAD,
        data={"directory": "a"},
        files=parts(("a.rpm", make_rpm()), ("a.rpm", make_rpm())),
        headers=root,
    )
    field = await client.post(
        UPLOAD,
        data={"directory": "a", "suite": "x"},
        files=parts(("a.rpm", make_rpm())),
        headers=root,
    )
    shallow = await client.post(UPLOAD, files=parts(("a.rpm", make_rpm())), headers=root)
    named = await client.post(
        UPLOAD, data={"directory": "a"}, files=parts(("a.txt", make_rpm())), headers=root
    )

    assert (twice.status_code, twice.json()["error"]["details"][0]["field"]) == (422, "file")
    assert (field.status_code, field.json()["error"]["details"][0]["field"]) == (422, "suite")
    assert (shallow.status_code, error_code(shallow)) == (400, "invalid_path")
    assert (named.status_code, error_code(named)) == (400, "invalid_path")


async def test_a_component_is_a_package_and_its_version_with_its_epoch(client, hosted, root):
    await upload(
        client, root, "x86_64/tool.rpm", make_rpm("megooarti-tool", "0.3", "2", "x86_64", epoch=2)
    )
    await upload(
        client, root, "aarch64/tool.rpm", make_rpm("megooarti-tool", "0.3", "2", "aarch64", epoch=2)
    )

    found = (await client.get(COMPONENTS, headers=root)).json()["items"]

    assert [(c["name"], c["version"]) for c in found] == [("megooarti-tool", "2:0.3-2")]
    detail = (await client.get(f"{COMPONENTS}/{found[0]['id']}", headers=root)).json()
    assert len(detail["files"]) == 2


async def test_a_package_is_found_by_its_summary_and_its_architectures(client, hosted, root):
    await upload(client, root, "a.rpm", make_rpm(summary="Prints a greeting"))
    await upload(
        client, root, "b.rpm", make_rpm("megooarti-other", arch="aarch64", summary="Other")
    )

    by_summary = await client.get("/api/v1/search", params={"q": "greeting"}, headers=root)
    by_arch = await client.get("/api/v1/search", params={"q": "aarch64"}, headers=root)

    assert [item["name"] for item in by_summary.json()["items"]] == ["megooarti-hello"]
    assert [item["name"] for item in by_arch.json()["items"]] == ["megooarti-other"]


async def test_a_component_is_installed_by_its_name_and_version(client, hosted, root):
    await upload(client, root, "tool.rpm", (DATA / TOOL).read_bytes())

    (component,) = (await client.get(COMPONENTS, headers=root)).json()["items"]
    detail = (await client.get(f"{COMPONENTS}/{component['id']}", headers=root)).json()

    assert detail["usage"] == [
        {"label": "dnf", "language": "shell", "text": "sudo dnf install megooarti-tool-2:0.3-2"}
    ]


async def test_deleting_a_component_takes_its_packages_out_of_the_metadata(client, hosted, root):
    await upload(client, root, "a.rpm", make_rpm())
    await upload(client, root, "b.rpm", make_rpm("megooarti-other"))

    found = (await client.get(COMPONENTS, headers=root)).json()["items"]
    (hello,) = [component for component in found if component["name"] == "megooarti-hello"]
    deleted = await client.delete(f"{COMPONENTS}/{hello['id']}", headers=root)
    listed = await primary(client, root)

    assert deleted.status_code == 204, deleted.text
    assert 'packages="1"' in listed and "<name>megooarti-other</name>" in listed
