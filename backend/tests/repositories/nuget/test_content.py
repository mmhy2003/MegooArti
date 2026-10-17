"""A NuGet repository through the content API: upload, components, search, usage and setup."""

from tests.accounts import error_code
from tests.repositories.nuget.conftest import create, push
from tests.repositories.nuget.packages import nupkg, nuspec, snupkg

CONTENT = "/api/v1/content"
UPLOAD = f"{CONTENT}/nuget-hosted/upload"
FOLDER = "v3/package/megooarti.hello/1.0.0"


async def test_packages_and_their_symbols_are_uploaded_in_a_form_where_pushes_put_them(
    client, hosted, root
):
    files = [("file", ("symbols.snupkg", snupkg())), ("file", ("hello.nupkg", nupkg()))]

    answer = await client.post(UPLOAD, files=files, headers=root)

    assert answer.status_code == 201, answer.text
    assert [file["path"] for file in answer.json()["files"]] == [
        f"{FOLDER}/megooarti.hello.1.0.0.nupkg",
        f"{FOLDER}/megooarti.hello.1.0.0.snupkg",
    ]


async def test_an_upload_that_is_not_a_package_stores_nothing(client, hosted, root):
    files = [("file", ("hello.nupkg", nupkg())), ("file", ("broken.nupkg", b"not a zip"))]

    answer = await client.post(UPLOAD, files=files, headers=root)

    assert (answer.status_code, error_code(answer)) == (400, "invalid_package")
    found = await client.get(f"{CONTENT}/nuget-hosted/components", headers=root)
    assert found.json()["items"] == []


async def test_a_version_is_a_component_with_its_files_and_how_to_use_it(client, hosted, root):
    await push(client, root, nupkg("MegooArti.Hello", "1.0.0-Beta"))
    await push(client, root, snupkg("MegooArti.Hello", "1.0.0-Beta"), symbols=True)

    (component,) = (await client.get(f"{CONTENT}/nuget-hosted/components", headers=root)).json()[
        "items"
    ]
    detail = (
        await client.get(f"{CONTENT}/nuget-hosted/components/{component['id']}", headers=root)
    ).json()

    assert (component["name"], component["version"]) == ("MegooArti.Hello", "1.0.0-beta")
    assert sorted(file["path"].rpartition("/")[2] for file in detail["files"]) == [
        "megooarti.hello.1.0.0-beta.nupkg",
        "megooarti.hello.1.0.0-beta.snupkg",
        "megooarti.hello.nuspec",
    ]
    usage = {snippet["label"]: snippet["text"] for snippet in detail["usage"]}
    assert usage == {
        "dotnet": "dotnet add package MegooArti.Hello --version 1.0.0-beta",
        "PackageReference": '<PackageReference Include="MegooArti.Hello" Version="1.0.0-beta" />',
        "Package Manager": "Install-Package MegooArti.Hello -Version 1.0.0-beta",
        "Chocolatey": "choco install MegooArti.Hello --version 1.0.0-beta",
        "PowerShell": "Install-PSResource MegooArti.Hello -Version 1.0.0-beta",
    }


async def test_megooartis_own_search_finds_a_package_by_its_description(client, hosted, root):
    await push(client, root, nupkg(description="Greets whoever asks."))

    found = await client.get("/api/v1/search", params={"q": "greets"}, headers=root)

    assert [item["name"] for item in found.json()["items"]] == ["MegooArti.Hello"]


async def test_a_repository_says_how_dotnet_is_given_it_as_a_source(client, hosted, root):
    view = (await client.get(f"{CONTENT}/nuget-hosted", headers=root)).json()

    dotnet, config, chocolatey, powershell = view["setup"]
    assert not dotnet["text"].startswith("#")
    assert dotnet["text"] == (
        'dotnet nuget add source "https://test/repository/nuget-hosted/index.json" '
        "--name nuget-hosted \\\n"
        '  --username "$MEGOOARTI_USER" --password "$MEGOOARTI_TOKEN" '
        "--store-password-in-clear-text"
    )
    assert config["label"] == "nuget.config"
    assert (
        '<add key="nuget-hosted" value="https://test/repository/nuget-hosted/index.json" />'
        in config["text"]
    )
    assert "<nuget-hosted>" in config["text"]
    assert '<add key="ClearTextPassword" value="%MEGOOARTI_TOKEN%" />' in config["text"]
    # Chocolatey is given V2's address, PowerShell V3's.
    assert chocolatey["text"] == (
        'choco source add --name="nuget-hosted" '
        '--source="https://test/repository/nuget-hosted/" \\\n'
        '  --user="$MEGOOARTI_USER" --password="$MEGOOARTI_TOKEN"'
    )
    assert powershell["language"] == "powershell"
    assert powershell["text"].startswith(
        "Register-PSResourceRepository -Name nuget-hosted "
        '-Uri "https://test/repository/nuget-hosted/index.json" -Trusted\n'
    )
    assert "-Credential $credential" in powershell["text"]


async def test_a_source_over_plain_http_is_allowed_so_and_a_name_is_made_an_element(
    client, db, root
):
    await create(db, "1nuget")

    view = (await client.get(f"http://plain.test{CONTENT}/1nuget", headers=root)).json()

    dotnet, config, *_ = (usage["text"] for usage in view["setup"])
    assert dotnet.startswith(
        "# Over plain HTTP: --allow-insecure-connections is the .NET SDK 9's and later's;"
        " with .NET 8, leave it out.\ndotnet nuget add source"
    )
    assert dotnet.endswith("--store-password-in-clear-text \\\n  --allow-insecure-connections")
    assert (
        'value="http://plain.test/repository/1nuget/index.json" allowInsecureConnections="true"'
        in config
    )
    assert "<_x0031_nuget>" in config


async def test_a_proxy_of_a_v2_feed_is_given_as_a_v2_source(client, root):
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "gallery",
            "format": "nuget",
            "type": "proxy",
            "format_config": {"protocol": "v2"},
            "proxy": {"remote_url": "https://www.powershellgallery.com/api/v2"},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text

    view = (await client.get(f"{CONTENT}/gallery", headers=root)).json()

    dotnet, config, chocolatey, powershell = (usage["text"] for usage in view["setup"])
    assert '"https://test/repository/gallery/" --name gallery' in dotnet
    assert 'value="https://test/repository/gallery/"' in config
    assert '--source="https://test/repository/gallery/"' in chocolatey
    assert '-Uri "https://test/repository/gallery" -ApiVersion v2 -Trusted' in powershell


async def test_a_hosted_repository_refuses_redeploy_unless_told_otherwise(client, root):
    made = await client.post(
        "/api/v1/repositories",
        json={"name": "nuget-made", "format": "nuget", "type": "hosted"},
        headers=root,
    )

    assert made.status_code == 201, made.text
    assert made.json()["hosted"] == {"deployment_policy": "disable_redeploy"}


async def test_a_refused_upload_leaves_no_file_of_a_package_it_stored_before(
    client, hosted, root, settings
):
    await push(client, root, nupkg("MegooArti.Hello", "1.0.0"))
    files = [
        ("file", ("new.nupkg", nupkg("Brand.New", "1.0.0"))),
        ("file", ("again.nupkg", nupkg("MegooArti.Hello", "1.0.0"))),
    ]

    answer = await client.post(UPLOAD, files=files, headers=root)

    assert answer.status_code == 409, answer.text
    store = settings.data_dir / "blobs" / "default"
    kept = [path.read_bytes() for path in store.rglob("*") if path.is_file()]
    assert nuspec("Brand.New", "1.0.0") not in kept
    assert nupkg("Brand.New", "1.0.0") not in kept
