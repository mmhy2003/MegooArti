"""An APT repository through the content API: upload, components, search and usage."""

from megooarti.repositories.apt import control
from tests.accounts import error_code
from tests.repositories.apt.conftest import URL, upload
from tests.repositories.apt.packages import control_text, make_deb

UPLOAD = "/api/v1/content/apt-hosted/upload"
COMPONENTS = "/api/v1/content/apt-hosted/components"
DISTS = f"{URL}/dists/stable"


def parts(*packages: tuple[str, bytes], field: str = "file") -> list:
    return [(field, package) for package in packages]


async def test_packages_uploaded_in_a_form_are_listed_as_uploaded_to_the_root(client, hosted, root):
    hello = ("hello.deb", make_deb())
    tool = ("tool.deb", make_deb(control_text(package="megooarti-tool", architecture="arm64")))

    response = await client.post(UPLOAD, files=parts(hello, tool), headers=root)
    listed = await client.get(f"{DISTS}/main/binary-arm64/Packages", headers=root)

    assert response.status_code == 201, response.text
    assert [file["path"] for file in response.json()["files"]] == [
        "pool/main/m/megooarti-hello/megooarti-hello_1.0-1_all.deb",
        "pool/main/m/megooarti-tool/megooarti-tool_1.0-1_arm64.deb",
    ]
    assert listed.text.count("Package: ") == 2


async def test_a_form_with_a_file_that_is_not_a_package_stores_none_of_them(client, hosted, root):
    response = await client.post(
        UPLOAD, files=parts(("hello.deb", make_deb()), ("notes.txt", b"notes")), headers=root
    )
    listed = await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert listed.text == ""


async def test_a_form_with_one_package_twice_or_a_field_it_does_not_take_is_refused(
    client, hosted, root
):
    twice = await client.post(
        UPLOAD, files=parts(("a.deb", make_deb()), ("b.deb", make_deb())), headers=root
    )
    field = await client.post(
        UPLOAD, data={"directory": "pool"}, files=parts(("a.deb", make_deb())), headers=root
    )

    assert (twice.status_code, twice.json()["error"]["details"][0]["field"]) == (422, "file")
    assert (field.status_code, field.json()["error"]["details"][0]["field"]) == (422, "directory")


async def test_a_component_is_a_package_and_its_version_with_its_epoch(client, hosted, root):
    await upload(client, root, make_deb(control_text(version="1:2.0~rc1-1", architecture="amd64")))
    await upload(client, root, make_deb(control_text(version="1:2.0~rc1-1", architecture="arm64")))

    found = (await client.get(COMPONENTS, headers=root)).json()["items"]

    assert [(c["name"], c["version"]) for c in found] == [("megooarti-hello", "1:2.0~rc1-1")]
    detail = (await client.get(f"{COMPONENTS}/{found[0]['id']}", headers=root)).json()
    assert len(detail["files"]) == 2
    assert detail["usage"] == [
        {
            "label": "apt",
            "language": "shell",
            "text": "sudo apt install megooarti-hello=1:2.0~rc1-1",
        }
    ]


async def test_a_package_is_found_by_its_description_and_its_architectures(client, hosted, root):
    described = control_text(
        description="Greets the world politely\n More.", architecture="riscv64"
    )
    await upload(client, root, make_deb(described))

    by_words = await client.get("/api/v1/search", params={"q": "greets politely"}, headers=root)
    by_architecture = await client.get("/api/v1/search", params={"q": "riscv64"}, headers=root)

    assert [item["name"] for item in by_words.json()["items"]] == ["megooarti-hello"]
    assert [item["name"] for item in by_architecture.json()["items"]] == ["megooarti-hello"]


async def test_deleting_a_component_takes_its_packages_out_of_the_indexes(client, hosted, root):
    await upload(client, root, make_deb())
    (component,) = (await client.get(COMPONENTS, headers=root)).json()["items"]

    deleted = await client.delete(f"{COMPONENTS}/{component['id']}", headers=root)
    listed = await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)

    assert deleted.status_code == 204
    assert listed.text == ""


async def test_what_a_package_said_of_itself_is_listed_as_it_said_it(client, hosted, root):
    text = control_text(extra="Depends: libc6 (>= 2.17)\nX-Custom: kept\n")
    await upload(client, root, make_deb(text))

    listed = await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)

    paragraph = control.parse(listed.text)
    assert control.get(paragraph, "Depends") == "libc6 (>= 2.17)"
    assert control.get(paragraph, "X-Custom") == "kept"
