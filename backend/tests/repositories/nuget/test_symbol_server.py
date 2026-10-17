"""The symbol server of NuGet repositories (section 8): the portable PDBs of each symbol
package kept at their keys, served to a debugger that names their checksum; a proxy's
symbol server asked with the debugger's checksum; a group's members asked in order."""

import uuid

import pytest

from megooarti.repositories.nuget import symbols
from tests.accounts import error_code
from tests.repositories.nuget.conftest import URL, create, push
from tests.repositories.nuget.packages import nupkg, portable_pdb, snupkg

PDB = portable_pdb()
KEPT = symbols.read("Hello.pdb", PDB)
KEY = KEPT.path.removeprefix("symbols/")
CHECKSUM = {"SymbolChecksum": f"SHA256:{KEPT.checksum.upper()}"}
SERVER = "http://symbols.test/download/symbols"


@pytest.fixture
async def pushed(client, hosted, root):
    """MegooArti.Hello 1.0.0, and its symbol package with one portable PDB."""
    assert (await push(client, root, nupkg())).status_code == 201
    assert (await push(client, root, snupkg(), symbols=True)).status_code == 201


async def test_a_pdb_is_served_at_its_key_to_whoever_names_its_checksum(client, root, pushed):
    named = await client.get(f"{URL}/{KEPT.path}", headers={**root, **CHECKSUM})
    unnamed = await client.get(f"{URL}/{KEPT.path}", headers=root)
    other = {"SymbolChecksum": f"SHA256:{'0' * 64}"}
    wrong = await client.get(f"{URL}/{KEPT.path}", headers={**root, **other})

    assert named.content == PDB
    assert named.headers["content-type"] == "application/octet-stream"
    assert unnamed.content == PDB
    assert wrong.status_code == 404


async def test_a_pdb_is_a_file_of_its_version_and_goes_with_it(client, root, pushed):
    detail = await client.get("/api/v1/content/nuget-hosted/components", headers=root)
    deleted = await client.delete(f"{URL}/api/v2/package/MegooArti.Hello/1.0.0", headers=root)
    after = await client.get(f"{URL}/{KEPT.path}", headers=root)

    assert detail.json()["items"][0]["name"] == "MegooArti.Hello"
    assert deleted.status_code == 204
    assert after.status_code == 404


async def test_deleting_a_symbol_package_deletes_its_pdbs(client, root, pushed):
    folder = "v3/package/megooarti.hello/1.0.0"

    deleted = await client.delete(
        "/api/v1/content/nuget-hosted/asset",
        params={"path": f"{folder}/megooarti.hello.1.0.0.snupkg"},
        headers=root,
    )
    after = await client.get(f"{URL}/{KEPT.path}", headers=root)
    package = await client.get(f"{URL}/{folder}/megooarti.hello.1.0.0.nupkg", headers=root)

    assert deleted.status_code == 204, deleted.text
    assert after.status_code == 404
    assert package.status_code == 200


@pytest.mark.parametrize(
    ("pdb", "said"),
    [
        (b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0", "Windows PDB"),
        (b"not a pdb", "not a portable PDB"),
    ],
    ids=["windows", "other"],
)
async def test_a_symbol_package_of_what_is_not_a_portable_pdb_is_refused(
    client, hosted, root, pdb, said
):
    await push(client, root, nupkg())
    pdbs = {"lib/net8.0/Good.pdb": PDB, "lib/net8.0/Hello.pdb": pdb}

    answer = await push(client, root, snupkg(pdbs=pdbs), symbols=True)
    kept = await client.get(f"{URL}/{KEPT.path.replace('hello.pdb', 'good.pdb')}", headers=root)
    folder = "v3/package/megooarti.hello/1.0.0"
    package = await client.get(f"{URL}/{folder}/megooarti.hello.1.0.0.snupkg", headers=root)

    assert (answer.status_code, error_code(answer)) == (400, "invalid_package")
    assert said in answer.json()["error"]["message"]
    assert kept.status_code == 404
    assert package.status_code == 404


async def test_a_symbol_package_pushed_again_keeps_only_its_own_pdbs(client, db, root):
    await create(db, hosted={"deployment_policy": "allow_redeploy"})
    await push(client, root, nupkg())
    await push(client, root, snupkg(), symbols=True)
    rebuilt = portable_pdb(guid=uuid.UUID("00000000-0000-0000-0000-000000000002"))

    again = await push(client, root, snupkg(pdbs={"lib/net8.0/Hello.pdb": rebuilt}), symbols=True)
    old = await client.get(f"{URL}/{KEPT.path}", headers=root)
    new = await client.get(f"{URL}/{symbols.read('Hello.pdb', rebuilt).path}", headers=root)

    assert again.status_code == 200, again.text
    assert old.status_code == 404
    assert new.content == rebuilt


@pytest.fixture
async def proxied(client, root, fake_remote):
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-org",
            "format": "nuget",
            "type": "proxy",
            "format_config": {"symbol_url": SERVER},
            "proxy": {"remote_url": "http://remote.test/v3/index.json"},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text
    fake_remote.files[f"download/symbols/{KEY}"] = PDB
    return fake_remote


async def test_a_proxy_asks_its_symbol_server_with_the_checksum_and_keeps_the_pdb(
    client, root, proxied
):
    address = f"/repository/nuget-org/{KEPT.path}"
    first = await client.get(address, headers={**root, **CHECKSUM})
    second = await client.get(address, headers={**root, **CHECKSUM})
    other = {"SymbolChecksum": f"SHA256:{'0' * 64}"}
    wrong = await client.get(address, headers={**root, **other})

    assert first.content == second.content == PDB
    asked = [seen for seen in proxied.requests if seen["path"] == f"/download/symbols/{KEY}"]
    assert len(asked) == 1  # kept
    assert asked[0]["headers"]["symbolchecksum"] == CHECKSUM["SymbolChecksum"]
    assert wrong.status_code == 404  # what is kept is not what was asked for


async def test_a_proxy_without_a_symbol_server_has_no_symbols(client, root, fake_remote):
    await client.post(
        "/api/v1/repositories",
        json={
            "name": "plain",
            "format": "nuget",
            "type": "proxy",
            "proxy": {"remote_url": "http://remote.test/v3/index.json"},
        },
        headers=root,
    )

    answer = await client.get(f"/repository/plain/{KEPT.path}", headers=root)

    assert answer.status_code == 404
    assert fake_remote.requests == []


async def test_a_group_serves_its_members_pdbs_in_order(client, root, pushed, proxied):
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-all",
            "format": "nuget",
            "type": "group",
            "group": {"members": ["nuget-hosted", "nuget-org"]},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text

    answer = await client.get(f"/repository/nuget-all/{KEPT.path}", headers={**root, **CHECKSUM})

    assert answer.content == PDB
    assert proxied.requests == []  # the hosted member had it


async def test_a_pdb_two_versions_carry_is_kept_once_and_both_pushes_succeed(client, hosted, root):
    # Packed twice with another version, as a CI build does: the same binaries, one PDB.
    for version in ("1.0.0", "1.0.1"):
        assert (await push(client, root, nupkg(version=version))).status_code == 201
        pushed = await push(client, root, snupkg(version=version), symbols=True)
        assert pushed.status_code == 201, pushed.text

    answer = await client.get(f"{URL}/{KEPT.path}", headers={**root, **CHECKSUM})

    assert answer.content == PDB


@pytest.mark.parametrize(
    "key",
    [
        KEPT.path.replace("hello.pdb", "Hello.pdb"),
        KEPT.path.replace(KEPT.guid, KEPT.guid.upper()),
        KEPT.path.replace("FFFFFFFF", "ffffffff"),
    ],
    ids=["name", "guid", "age"],
)
async def test_a_key_is_matched_without_regard_to_case(client, root, pushed, key):
    for method in ("GET", "HEAD"):
        answer = await client.request(method, f"{URL}/{key}", headers={**root, **CHECKSUM})
        assert answer.status_code == 200


async def test_a_symbol_server_that_fails_does_not_stop_the_proxys_feed(client, root, proxied):
    proxied.statuses[f"download/symbols/{KEY}"] = 503

    failed = await client.get(f"/repository/nuget-org/{KEPT.path}", headers={**root, **CHECKSUM})
    status = await client.get("/api/v1/repositories/nuget-org", headers=root)

    assert failed.status_code == 502
    # Recorded, and not counted towards leaving the remote alone.
    assert status.json()["status"]["auto_blocked_until"] is None
    assert status.json()["status"]["last_error"]
