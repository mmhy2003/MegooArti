"""A hosted NuGet repository over V3: pushed to, read from, and deleted from."""

import pytest
from sqlalchemy import update

from megooarti.repositories.models import Component
from megooarti.repositories.nuget import documents
from tests.accounts import error_code
from tests.repositories.nuget.conftest import BASE, URL, create, push
from tests.repositories.nuget.packages import nupkg, nuspec, snupkg


async def test_the_service_index_names_each_resource_at_this_repositorys_address(
    client, hosted, root
):
    answer = await client.get(f"{URL}/index.json", headers=root)

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/json")
    resources = {item["@type"]: item["@id"] for item in answer.json()["resources"]}
    assert resources["PackageBaseAddress/3.0.0"] == f"{BASE}v3/package/"
    assert resources["PackagePublish/2.0.0"] == f"{BASE}api/v2/package"
    assert resources["SymbolPackagePublish/4.9.0"] == f"{BASE}api/v2/symbolpackage"
    assert resources["RegistrationsBaseUrl/3.6.0"] == f"{BASE}v3/registration/"
    assert resources["SearchQueryService/3.5.0"] == f"{BASE}v3/search"
    assert resources["SearchAutocompleteService/3.5.0"] == f"{BASE}v3/autocomplete"


async def test_a_pushed_package_is_listed_fetched_and_described(client, hosted, root):
    package = nupkg("MegooArti.Hello", "1.0.0-Beta.1", more="<title>Hello</title>")

    pushed = await push(client, root, package)

    assert pushed.status_code == 201, pushed.text
    listed = await client.get(f"{URL}/v3/package/megooarti.hello/index.json", headers=root)
    assert listed.json() == {"versions": ["1.0.0-beta.1"]}
    fetched = await client.get(
        f"{URL}/v3/package/megooarti.hello/1.0.0-beta.1/megooarti.hello.1.0.0-beta.1.nupkg",
        headers=root,
    )
    assert fetched.content == package
    spec = await client.get(
        f"{URL}/v3/package/megooarti.hello/1.0.0-beta.1/megooarti.hello.nuspec", headers=root
    )
    assert spec.content == nuspec("MegooArti.Hello", "1.0.0-Beta.1", more="<title>Hello</title>")
    registration = (
        await client.get(f"{URL}/v3/registration/megooarti.hello/index.json", headers=root)
    ).json()
    (page,) = registration["items"]
    (item,) = page["items"]
    entry = item["catalogEntry"]
    assert (entry["id"], entry["version"], entry["title"]) == (
        "MegooArti.Hello",
        "1.0.0-Beta.1",
        "Hello",
    )
    assert entry["listed"] is True
    content = f"{BASE}v3/package/megooarti.hello/1.0.0-beta.1/megooarti.hello.1.0.0-beta.1.nupkg"
    assert item["packageContent"] == entry["packageContent"] == content
    leaf = await client.get(
        f"{URL}/v3/registration/megooarti.hello/1.0.0-beta.1.json", headers=root
    )
    assert leaf.json()["packageContent"] == content


async def test_a_version_is_pushed_once_unless_redeploy_is_allowed(client, db, hosted, root):
    assert (await push(client, root, nupkg())).status_code == 201

    again = await push(client, root, nupkg(description="Changed."))

    # What `dotnet nuget push --skip-duplicate` takes for "already there".
    assert again.status_code == 409
    allowing = await create(db, "nuget-open", hosted={"deployment_policy": "allow_redeploy"})
    assert (await push(client, root, nupkg(), repository=allowing.name)).status_code == 201
    replaced = await push(client, root, nupkg(description="Changed."), repository="nuget-open")
    assert replaced.status_code == 200


async def test_an_api_key_is_an_api_token_and_nothing_else(client, hosted, make_user, make_token):
    user = await make_user("ci", roles=["admin"])
    token = await make_token(user)

    pushed = await push(client, {"X-NuGet-ApiKey": token}, nupkg())
    refused = await push(client, {"X-NuGet-ApiKey": "not-a-token"}, nupkg("Other"))
    anonymous = await push(client, {}, nupkg("Other"))

    assert pushed.status_code == 201
    assert refused.status_code == 401
    assert anonymous.status_code == 401
    assert refused.headers["WWW-Authenticate"].startswith("Basic")


async def test_an_id_is_matched_without_regard_to_case_and_spelled_as_first_pushed(
    client, hosted, root
):
    await push(client, root, nupkg("MegooArti.Hello", "1.0.0"))
    await push(client, root, nupkg("megooarti.HELLO", "2.0.0"))

    listed = await client.get(f"{URL}/v3/package/megooarti.hello/index.json", headers=root)
    registration = await client.get(
        f"{URL}/v3/registration/megooarti.hello/index.json", headers=root
    )

    assert listed.json() == {"versions": ["1.0.0", "2.0.0"]}
    entries = [item["catalogEntry"]["id"] for item in registration.json()["items"][0]["items"]]
    assert entries == ["MegooArti.Hello", "MegooArti.Hello"]


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (nupkg(spec=nuspec(version="one")), "its version is not one NuGet takes"),
        (b"not a zip", "it is not a zip file"),
    ],
    ids=["version", "zip"],
)
async def test_what_is_not_a_package_is_refused_and_nothing_is_kept(
    client, hosted, root, body, said
):
    answer = await push(client, root, body)

    assert (answer.status_code, error_code(answer)) == (400, "invalid_package")
    assert said in answer.json()["error"]["message"]
    assert (await client.get(f"{URL}/v3/search", headers=root)).json()["totalHits"] == 0


async def test_a_push_is_one_package_in_a_form(client, hosted, root):
    bare = await client.put(f"{URL}/api/v2/package", content=nupkg(), headers=root)
    two = await client.put(
        f"{URL}/api/v2/package",
        files=[("a", ("a.nupkg", nupkg("A"))), ("b", ("b.nupkg", nupkg("B")))],
        headers=root,
    )

    assert (bare.status_code, error_code(bare)) == (400, "invalid_package")
    assert (two.status_code, error_code(two)) == (400, "invalid_package")


async def test_a_symbol_package_goes_beside_its_package_and_only_there(client, hosted, root):
    early = await push(client, root, snupkg(), symbols=True)
    await push(client, root, nupkg())
    pushed = await push(client, root, snupkg(), symbols=True)
    package_as_symbols = await push(client, root, nupkg("Other"), symbols=True)

    assert early.status_code == 404
    assert pushed.status_code == 201
    kept = await client.get(
        f"{URL}/v3/package/megooarti.hello/1.0.0/megooarti.hello.1.0.0.snupkg", headers=root
    )
    assert kept.content == snupkg()
    assert (package_as_symbols.status_code, error_code(package_as_symbols)) == (
        400,
        "invalid_package",
    )


async def test_a_deleted_version_is_gone_with_every_file_of_it(client, hosted, root):
    await push(client, root, nupkg("MegooArti.Hello", "1.0.0"))
    await push(client, root, snupkg(), symbols=True)
    await push(client, root, nupkg("MegooArti.Hello", "2.0.0"))

    deleted = await client.delete(f"{URL}/api/v2/package/MegooArti.Hello/1.0.0", headers=root)
    again = await client.delete(f"{URL}/api/v2/package/MegooArti.Hello/1.0.0", headers=root)

    assert deleted.status_code == 204
    assert again.status_code == 404
    listed = await client.get(f"{URL}/v3/package/megooarti.hello/index.json", headers=root)
    assert listed.json() == {"versions": ["2.0.0"]}
    for file in (
        "megooarti.hello.1.0.0.nupkg",
        "megooarti.hello.nuspec",
        "megooarti.hello.1.0.0.snupkg",
    ):
        gone = await client.get(f"{URL}/v3/package/megooarti.hello/1.0.0/{file}", headers=root)
        assert gone.status_code == 404, file


async def test_deleting_needs_the_permission_to_delete(client, hosted, root, pusher):
    await push(client, root, nupkg())

    refused = await client.delete(f"{URL}/api/v2/package/MegooArti.Hello/1.0.0", headers=pusher)

    assert refused.status_code == 403
    assert (await push(client, pusher, nupkg("Other"))).status_code == 201


async def test_deleting_a_package_in_the_ui_deletes_its_version_and_its_nuspec_goes_with_it(
    client, hosted, root
):
    await push(client, root, nupkg())
    folder = "v3/package/megooarti.hello/1.0.0"

    spec = await client.delete(
        "/api/v1/content/nuget-hosted/asset",
        params={"path": f"{folder}/megooarti.hello.nuspec"},
        headers=root,
    )
    package = await client.delete(
        "/api/v1/content/nuget-hosted/asset",
        params={"path": f"{folder}/megooarti.hello.1.0.0.nupkg"},
        headers=root,
    )

    assert (spec.status_code, error_code(spec)) == (409, "managed_by_format")
    assert package.status_code == 204
    gone = await client.get(f"{URL}/{folder}/megooarti.hello.nuspec", headers=root)
    assert gone.status_code == 404


async def test_a_read_only_repository_takes_no_push(client, db, root):
    await create(db, "nuget-frozen", hosted={"deployment_policy": "read_only"})

    answer = await push(client, root, nupkg(), repository="nuget-frozen")

    assert answer.status_code == 403


async def test_a_registration_of_up_to_128_versions_inlines_them_in_pages_of_64(
    client, hosted, root
):
    for minor in range(65):
        assert (await push(client, root, nupkg(version=f"1.{minor}.0"))).status_code == 201

    registration = (
        await client.get(f"{URL}/v3/registration/megooarti.hello/index.json", headers=root)
    ).json()

    assert registration["count"] == 2
    first, second = registration["items"]
    assert (first["count"], first["lower"], first["upper"]) == (documents.PAGE, "1.0.0", "1.63.0")
    assert (second["count"], second["lower"], second["upper"]) == (1, "1.64.0", "1.64.0")
    assert [len(page["items"]) for page in registration["items"]] == [64, 1]


async def test_a_registration_of_more_versions_lists_its_pages_and_serves_each(
    client, hosted, root
):
    for minor in range(documents.INLINED_MOST + 1):
        assert (await push(client, root, nupkg(version=f"1.{minor}.0"))).status_code == 201
    address = f"{URL}/v3/registration/megooarti.hello"

    index = (await client.get(f"{address}/index.json", headers=root)).json()

    assert index["count"] == 3
    assert all("items" not in page for page in index["items"])
    assert [(page["count"], page["lower"], page["upper"]) for page in index["items"]] == [
        (64, "1.0.0", "1.63.0"),
        (64, "1.64.0", "1.127.0"),
        (1, "1.128.0", "1.128.0"),
    ]
    served = []
    for page in index["items"]:
        assert page["@type"] == "catalog:CatalogPage"
        assert (
            page["@id"]
            == f"{BASE}v3/registration/megooarti.hello/page/{page['lower']}/{page['upper']}.json"
        )
        fetched = await client.get(page["@id"].replace(BASE, f"{URL}/"), headers=root)
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["@id"] == page["@id"]
        assert body["parent"] == index["@id"]
        assert (body["count"], body["lower"], body["upper"]) == (
            page["count"],
            page["lower"],
            page["upper"],
        )
        assert len(body["items"]) == page["count"]
        served += [item["catalogEntry"]["version"] for item in body["items"]]
    assert served == [f"1.{minor}.0" for minor in range(documents.INLINED_MOST + 1)]
    unknown = await client.get(f"{address}/page/1.0.0/1.62.0.json", headers=root)
    assert unknown.status_code == 404
    elsewhere = await client.get(
        f"{URL}/v3/registration/nothing.here/page/1.0.0/1.63.0.json", headers=root
    )
    assert elsewhere.status_code == 404


async def test_a_version_list_is_written_from_the_versions_alone(client, db, hosted, root):
    await push(client, root, nupkg(version="1.0.0"))
    await push(client, root, nupkg(version="2.0.0"))
    # What a version said of itself is not read for a list: with it gone, it is listed.
    await db.execute(update(Component).values(attributes=None))
    await db.commit()

    listed = await client.get(f"{URL}/v3/package/megooarti.hello/index.json", headers=root)

    assert listed.json() == {"versions": ["1.0.0", "2.0.0"]}


@pytest.mark.parametrize(
    "path",
    [
        "v3/package/megooarti.hello/index.json",
        "v3/registration/megooarti.hello/index.json",
        "v3/registration/megooarti.hello/1.0.0.json",
        "v3/package/MegooArti.Hello/index.json",
        "v3/other",
        "",
    ],
)
async def test_what_is_not_there_is_not_found(client, hosted, root, path):
    assert (await client.get(f"{URL}/{path}", headers=root)).status_code == 404


async def test_each_address_takes_its_own_methods(client, hosted, root):
    assert (await client.get(f"{URL}/api/v2/package", headers=root)).status_code == 405
    assert (await client.put(f"{URL}/index.json", content=b"", headers=root)).status_code == 405
    assert (await client.delete(f"{URL}/index.json", headers=root)).status_code == 405


async def test_an_api_key_is_taken_by_package_clients_only(client, make_user, make_token):
    user = await make_user("ci", roles=["admin"])
    token = await make_token(user)

    # The JSON API takes a token as a bearer token, never in NuGet's header.
    answer = await client.get("/api/v1/me/tokens", headers={"X-NuGet-ApiKey": token})

    assert answer.status_code == 401


async def test_the_first_push_of_an_id_takes_a_lock_on_the_id(client, hosted, root, monkeypatch):
    from megooarti.repositories.content import RepositoryContext

    locked = []
    real = RepositoryContext.lock

    async def recording(self, name):
        locked.append(name)
        await real(self, name)

    monkeypatch.setattr(RepositoryContext, "lock", recording)

    pushed = await push(client, root, nupkg("MegooArti.Hello", "1.0.0"))

    assert pushed.status_code == 201
    assert "id:megooarti.hello" in locked
