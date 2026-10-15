"""A hosted apk repository, as apk and an uploader use it."""

import io
import tarfile
import zlib

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from megooarti.repositories.apk import format as apk_format
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.apk.conftest import KEY, MAIN, URL, create, upload
from tests.repositories.apk.packages import DATA, HELLO, TOOL, make_apk, pkginfo

X86 = "v3.24/main/x86_64"


def opened(index: bytes) -> tuple[bytes, bytes, dict[str, bytes]]:
    """An index's signature, its second stream as packed, and the files of that stream."""
    first = zlib.decompressobj(wbits=31)
    signature_tar = first.decompress(index)
    packed = first.unused_data
    second = zlib.decompressobj(wbits=31).decompress(packed)
    with tarfile.open(fileobj=io.BytesIO(signature_tar + b"\0" * 1024)) as tar:
        signature = tar.extractfile(tar.getmembers()[0]).read()
    with tarfile.open(fileobj=io.BytesIO(second)) as tar:
        files = {member.name: tar.extractfile(member).read() for member in tar.getmembers()}
    return signature, packed, files


def records(index: bytes) -> list[dict[str, str]]:
    text = opened(index)[2]["APKINDEX"].decode()
    return [
        dict(line.split(":", 1) for line in chunk.splitlines())
        for chunk in text.split("\n\n")
        if chunk.strip()
    ]


async def test_a_package_put_to_its_architectures_directory_is_kept_there(client, hosted, root):
    package = (DATA / TOOL).read_bytes()

    response = await upload(client, root, f"{X86}/{TOOL}", package)
    fetched = await client.get(f"{URL}/{X86}/{TOOL}", headers=root)

    assert response.status_code == 201, response.text
    assert fetched.content == package
    assert fetched.headers["content-type"] == "application/gzip"


async def test_a_package_put_again_replaces_it_as_the_policy_allows(client, db, root):
    await create(db, "apk-hosted")
    await create(db, "apk-releases", hosted={"deployment_policy": "disable_redeploy"})
    path = f"{X86}/megooarti-hello-1.0-r0.apk"

    assert (await upload(client, root, path, make_apk())).status_code == 201
    assert (await upload(client, root, path, make_apk())).status_code == 204
    assert (
        await upload(client, root, path, make_apk(), repository="apk-releases")
    ).status_code == 201
    again = await upload(client, root, path, make_apk(), repository="apk-releases")
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")


@pytest.mark.parametrize(
    ("path", "package", "said"),
    [
        ("v3.24/main/aarch64/megooarti-tool-0.3_rc1-r2.apk", TOOL, "a package for x86_64"),
        (f"{X86}/tool.apk", TOOL, "as megooarti-tool-0.3_rc1-r2.apk"),
    ],
)
async def test_a_package_put_where_apk_would_not_ask_for_it_is_refused(
    client, hosted, root, settings, path, package, said
):
    response = await upload(client, root, path, (DATA / package).read_bytes())

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert said in response.json()["error"]["message"]
    store = settings.data_dir / "blobs" / "default"
    assert [path for path in store.rglob("*") if path.is_file()] == []


async def test_a_package_for_no_architecture_may_be_put_in_any_architectures_directory(
    client, hosted, root
):
    for arch in ("x86_64", "aarch64"):
        response = await upload(
            client, root, f"v3.24/main/{arch}/{HELLO}", (DATA / HELLO).read_bytes()
        )
        assert response.status_code == 201, response.text

    index = (await client.get(f"{MAIN}/aarch64/APKINDEX.tar.gz", headers=root)).content

    assert [(r["P"], r["A"]) for r in records(index)] == [("megooarti-hello", "aarch64")]


@pytest.mark.parametrize(
    ("package", "reason"),
    [
        (b"PK\x03\x04 a zip file", "not an apk package"),
        (b"ADBd" + b"\0" * 64, "apk-tools 3's package format"),
    ],
)
async def test_what_is_not_an_apk_package_is_refused_and_nothing_is_kept(
    client, hosted, root, settings, package, reason
):
    response = await upload(client, root, f"{X86}/a-1.0-r0.apk", package)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert reason in response.json()["error"]["message"]
    store = settings.data_dir / "blobs" / "default"
    assert [path for path in store.rglob("*") if path.is_file()] == []


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("notes.txt", 400, "invalid_path"),
        ("a-1.0-r0.apk", 400, "invalid_path"),
        (f"{X86}/APKINDEX.tar.gz", 405, "method_not_allowed"),
        (KEY, 405, "method_not_allowed"),
    ],
)
async def test_a_package_is_put_only_where_a_package_can_be(
    client, hosted, root, path, status, code
):
    response = await upload(client, root, path, make_apk())

    assert (response.status_code, error_code(response)) == (status, code)


async def test_an_upload_needs_credentials_and_the_right_to_add(client, db, hosted, make_user):
    await roles.create_role(db, "readers", "", ["repository:apk:apk-hosted:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    path = f"{X86}/megooarti-hello-1.0-r0.apk"

    nobody = await upload(client, {}, path, make_apk())
    reader = await upload(client, basic("rae", PASSWORD), path, make_apk())

    assert nobody.status_code == 401
    assert reader.status_code == 403


async def test_the_index_lists_the_packages_and_is_signed_with_the_repositorys_key(
    client, hosted, root
):
    await upload(client, root, f"{X86}/{HELLO}", (DATA / HELLO).read_bytes())
    await upload(client, root, f"{X86}/{TOOL}", (DATA / TOOL).read_bytes())

    index = await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers=root)
    key = await client.get(f"{URL}/{KEY}", headers=root)

    signature, packed, files = opened(index.content)
    public = serialization.load_pem_public_key(key.content)
    public.verify(signature, packed, padding.PKCS1v15(), hashes.SHA1())
    assert [r["P"] for r in records(index.content)] == ["megooarti-hello", "megooarti-tool"]
    assert files["DESCRIPTION"] == b"MegooArti apk-hosted"
    assert index.headers["content-type"] == "application/gzip"
    assert key.headers["content-type"] == "application/x-pem-file"


async def test_a_directory_without_packages_has_a_signed_empty_index(client, hosted, root):
    index = await client.get(f"{MAIN}/riscv64/APKINDEX.tar.gz", headers=root)

    assert index.status_code == 200
    assert opened(index.content)[2]["APKINDEX"] == b""


async def test_each_directory_lists_only_its_own_packages(client, hosted, root):
    await upload(client, root, f"{X86}/{TOOL}", (DATA / TOOL).read_bytes())
    await upload(
        client,
        root,
        "v3.23/main/x86_64/megooarti-hello-1.0-r0.apk",
        make_apk(),
    )

    ours = records((await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers=root)).content)
    older = records(
        (await client.get(f"{URL}/v3.23/main/x86_64/APKINDEX.tar.gz", headers=root)).content
    )

    assert [r["P"] for r in ours] == ["megooarti-tool"]
    assert [r["P"] for r in older] == ["megooarti-hello"]


async def test_the_indexes_are_written_once_for_each_revision(client, hosted, root, monkeypatch):
    written = []
    write = apk_format._written

    def counted(*arguments):
        written.append(1)
        return write(*arguments)

    monkeypatch.setattr(apk_format, "_written", counted)

    await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers=root)
    await client.get(f"{MAIN}/aarch64/APKINDEX.tar.gz", headers=root)
    assert len(written) == 1
    await upload(client, root, f"{X86}/megooarti-hello-1.0-r0.apk", make_apk())
    await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers=root)
    assert len(written) == 2


async def test_an_index_is_sent_again_whatever_date_a_client_has_unless_it_has_these_bytes(
    client, hosted, root
):
    await upload(client, root, f"{X86}/megooarti-hello-1.0-r0.apk", make_apk())
    before = await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers=root)
    await upload(
        client, root, f"{X86}/megooarti-hello-2.0-r0.apk", make_apk(pkginfo(version="2.0-r0"))
    )
    later = {"If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"}

    after = await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers={**root, **later})
    same = await client.get(
        f"{URL}/{X86}/APKINDEX.tar.gz", headers={**root, "If-None-Match": after.headers["etag"]}
    )

    assert after.status_code == 200 and after.content != before.content
    assert same.status_code == 304


async def test_a_deleted_package_leaves_the_index(client, hosted, root):
    await upload(client, root, f"{X86}/megooarti-hello-1.0-r0.apk", make_apk())
    await upload(
        client, root, f"{X86}/megooarti-hello-2.0-r0.apk", make_apk(pkginfo(version="2.0-r0"))
    )

    deleted = await client.delete(f"{URL}/{X86}/megooarti-hello-1.0-r0.apk", headers=root)
    index = await client.get(f"{URL}/{X86}/APKINDEX.tar.gz", headers=root)

    assert deleted.status_code == 204
    assert [r["V"] for r in records(index.content)] == ["2.0-r0"]


async def test_the_key_is_the_one_the_api_shows_under_the_name_apk_finds_it_by(
    admin_client, hosted
):
    shown = (await admin_client.get("/api/v1/repositories/apk-hosted/signing-key")).json()

    served = await admin_client.get(f"{URL}/{KEY}")

    assert served.text == shown["public_key"]
    assert f'filename="{KEY}"' in served.headers["content-disposition"]


@pytest.mark.parametrize("path", ["v3.24/main/x86_64/a-1.0-r0.apk", "README", "other.rsa.pub"])
async def test_what_the_repository_does_not_have_is_not_found(client, hosted, root, path):
    assert (await client.get(f"{URL}/{path}", headers=root)).status_code == 404


async def test_a_repository_is_read_with_the_right_to_read(client, db, hosted, make_user):
    await roles.create_role(db, "readers", "", ["repository:apk:apk-hosted:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    assert (await client.get(f"{URL}/{X86}/APKINDEX.tar.gz")).status_code == 401
    for path in (f"{X86}/APKINDEX.tar.gz", KEY):
        response = await client.get(f"{URL}/{path}", headers=basic("rae", PASSWORD))
        assert response.status_code == 200, path


@pytest.mark.parametrize(
    ("type", "format_config", "field"),
    [
        ("hosted", {"suite": "stable"}, "format_config"),
        ("proxy", {"remote_keys": "x"}, "format_config"),
    ],
)
async def test_settings_that_cannot_be_used_are_refused(admin_client, type, format_config, field):
    body = {"name": "apk", "format": "apk", "type": type, "format_config": format_config}
    if type == "proxy":
        body["proxy"] = {"remote_url": "https://dl-cdn.alpinelinux.org/alpine"}

    refused = await admin_client.post("/api/v1/repositories", json=body)

    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_a_group_of_apk_repositories_is_not_made_yet(admin_client):
    refused = await admin_client.post(
        "/api/v1/repositories",
        json={"name": "apk-all", "format": "apk", "type": "group", "group": {"members": []}},
    )

    assert refused.status_code == 422
