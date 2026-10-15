"""An apk repository through the content API: upload, components, search and usage."""

import io
import tarfile
import zlib

from tests.accounts import error_code
from tests.repositories.apk.conftest import URL, upload
from tests.repositories.apk.packages import DATA, HELLO, TOOL, make_apk, pkginfo

UPLOAD = "/api/v1/content/apk-hosted/upload"
COMPONENTS = "/api/v1/content/apk-hosted/components"
X86 = "v3.24/main/x86_64"


def parts(*packages: tuple[str, bytes], field: str = "file") -> list:
    return [(field, package) for package in packages]


async def names(client, headers, directory: str = X86) -> list[str]:
    index = (await client.get(f"{URL}/{directory}/APKINDEX.tar.gz", headers=headers)).content
    first = zlib.decompressobj(wbits=31)
    first.decompress(index)
    second = zlib.decompressobj(wbits=31).decompress(first.unused_data)
    with tarfile.open(fileobj=io.BytesIO(second)) as tar:
        text = tar.extractfile("APKINDEX").read().decode()
    return [line[2:] for line in text.splitlines() if line.startswith("P:")]


async def test_packages_uploaded_in_a_form_are_kept_under_the_names_apk_asks_for(
    client, hosted, root
):
    hello = ("hello.apk", (DATA / HELLO).read_bytes())
    tool = ("tool.apk", (DATA / TOOL).read_bytes())

    response = await client.post(
        UPLOAD, data={"directory": f"/{X86}/"}, files=parts(hello, tool), headers=root
    )

    assert response.status_code == 201, response.text
    assert [file["path"] for file in response.json()["files"]] == [
        f"{X86}/{HELLO}",
        f"{X86}/{TOOL}",
    ]
    assert await names(client, root) == ["megooarti-hello", "megooarti-tool"]


async def test_a_form_with_a_file_that_is_not_a_package_stores_none_of_them(client, hosted, root):
    response = await client.post(
        UPLOAD,
        data={"directory": X86},
        files=parts(("a.apk", make_apk()), ("b.apk", b"not a package")),
        headers=root,
    )

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert await names(client, root) == []


async def test_a_form_that_cannot_be_kept_as_it_is_is_refused(client, hosted, root):
    tool = (DATA / TOOL).read_bytes()

    twice = await client.post(
        UPLOAD, data={"directory": X86}, files=parts(("a.apk", tool), ("b.apk", tool)), headers=root
    )
    field = await client.post(
        UPLOAD, data={"directory": X86, "suite": "x"}, files=parts(("a.apk", tool)), headers=root
    )
    elsewhere = await client.post(
        UPLOAD, data={"directory": "v3.24/main/aarch64"}, files=parts(("a.apk", tool)), headers=root
    )

    assert (twice.status_code, twice.json()["error"]["details"][0]["field"]) == (422, "file")
    assert (field.status_code, field.json()["error"]["details"][0]["field"]) == (422, "suite")
    assert (elsewhere.status_code, error_code(elsewhere)) == (400, "invalid_path")


async def test_a_component_is_a_package_and_its_version(client, hosted, root):
    await upload(client, root, f"{X86}/{HELLO}", (DATA / HELLO).read_bytes())
    await upload(client, root, f"v3.24/main/aarch64/{HELLO}", (DATA / HELLO).read_bytes())

    found = (await client.get(COMPONENTS, headers=root)).json()["items"]

    assert [(c["name"], c["version"]) for c in found] == [("megooarti-hello", "1.0-r0")]
    detail = (await client.get(f"{COMPONENTS}/{found[0]['id']}", headers=root)).json()
    assert len(detail["files"]) == 2
    assert detail["usage"] == [
        {"label": "apk", "language": "shell", "text": "apk add megooarti-hello=1.0-r0"}
    ]


async def test_a_package_is_found_by_its_description_and_its_architectures(client, hosted, root):
    await upload(
        client,
        root,
        "v3.24/main/riscv64/megooarti-hello-1.0-r0.apk",
        make_apk(pkginfo(description="Greets the world politely", arch="riscv64")),
    )

    by_words = await client.get("/api/v1/search", params={"q": "politely"}, headers=root)
    by_arch = await client.get("/api/v1/search", params={"q": "riscv64"}, headers=root)

    assert [item["name"] for item in by_words.json()["items"]] == ["megooarti-hello"]
    assert [item["name"] for item in by_arch.json()["items"]] == ["megooarti-hello"]


async def test_deleting_a_component_takes_its_packages_out_of_the_index(client, hosted, root):
    await upload(client, root, f"{X86}/{HELLO}", (DATA / HELLO).read_bytes())
    (component,) = (await client.get(COMPONENTS, headers=root)).json()["items"]

    deleted = await client.delete(f"{COMPONENTS}/{component['id']}", headers=root)

    assert deleted.status_code == 204
    assert await names(client, root) == []
