"""A hosted APT repository, as apt and an uploader use it."""

import gzip
import hashlib
import lzma

import pysequoia
import pytest

from megooarti.repositories.apt import control
from megooarti.repositories.apt import format as apt_format
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.apt.conftest import URL, create, upload
from tests.repositories.apt.packages import DATA, REAL, control_text, make_deb

DISTS = f"{URL}/dists/stable"
HELLO = "pool/main/m/megooarti-hello/megooarti-hello_1.0-1_all.deb"


def paragraphs(data: bytes) -> list[control.Paragraph]:
    return [control.parse(part) for part in data.decode().split("\n\n") if part.strip()]


def verified(signed: bytes, public_key: bytes, signature: bytes | None = None) -> bytes:
    """What a signature vouches for, checked with a public key. Raises if it does not."""
    certificate = pysequoia.Cert.from_bytes(public_key)
    if signature is None:
        return pysequoia.verify(bytes=signed, store=lambda _: [certificate]).bytes
    pysequoia.verify(
        bytes=signed, store=lambda _: [certificate], signature=pysequoia.Sig.from_bytes(signature)
    )
    return signed


async def test_a_package_uploaded_to_the_root_is_kept_where_debian_keeps_it(client, hosted, root):
    package = (DATA / REAL["gzip"]).read_bytes()

    response = await upload(client, root, package)
    fetched = await client.get(f"{URL}/{HELLO}", headers=root)

    assert response.status_code == 201, response.text
    assert response.headers["location"] == f"https://test{URL}/{HELLO}"
    assert fetched.content == package
    assert fetched.headers["content-type"] == "application/vnd.debian.binary-package"


async def test_a_package_may_be_posted_as_well(client, hosted, root):
    response = await upload(client, root, make_deb(), method="POST")

    assert response.status_code == 201


async def test_a_package_uploaded_again_replaces_it_as_the_policy_allows(client, db, root):
    await create(db, "apt-hosted")
    await create(db, "apt-releases", hosted={"deployment_policy": "disable_redeploy"})

    assert (await upload(client, root, make_deb())).status_code == 201
    assert (await upload(client, root, make_deb())).status_code == 204
    assert (await upload(client, root, make_deb(), repository="apt-releases")).status_code == 201
    again = await upload(client, root, make_deb(), repository="apt-releases")
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")


async def test_what_is_not_a_package_is_refused_and_nothing_is_kept(client, hosted, root, settings):
    response = await upload(client, root, b"PK\x03\x04 a zip file")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert "not an ar archive" in response.json()["error"]["message"]
    store = settings.data_dir / "blobs" / "default"
    assert [path for path in store.rglob("*") if path.is_file()] == []


async def test_an_upload_needs_credentials_and_the_right_to_add(client, db, hosted, make_user):
    await roles.create_role(db, "readers", "", ["repository:apt:apt-hosted:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    nobody = await upload(client, {}, make_deb())
    reader = await upload(client, basic("rae", PASSWORD), make_deb())

    assert nobody.status_code == 401
    assert (reader.status_code, error_code(reader)) == (403, "forbidden")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ""),
        ("PUT", "pool/main/h/hello/hello_1.0_all.deb"),
        ("PUT", "dists/stable/InRelease"),
        ("DELETE", "dists/stable/InRelease"),
    ],
)
async def test_a_package_has_one_way_in(client, hosted, root, method, path):
    response = await client.request(method, f"{URL}/{path}", content=make_deb(), headers=root)

    assert response.status_code == 405


async def test_the_indexes_list_each_package_with_its_file_and_checksums(client, hosted, root):
    package = (DATA / REAL["xz"]).read_bytes()
    await upload(client, root, package)

    listed = await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)

    (paragraph,) = paragraphs(listed.content)
    expected = {
        "Package": "megooarti-hello",
        "Version": "1:2.0~rc1-1",
        "Architecture": "amd64",
        "Filename": "pool/main/m/megooarti-hello/megooarti-hello_2.0~rc1-1_amd64.deb",
        "Size": str(len(package)),
        "MD5sum": hashlib.md5(package).hexdigest(),
        "SHA1": hashlib.sha1(package).hexdigest(),
        "SHA256": hashlib.sha256(package).hexdigest(),
        "Description": (
            "Says hello (xz)\n A package made for the tests of MegooArti.\n .\n It prints one line."
        ),
    }
    assert {name: control.get(paragraph, name) for name in expected} == expected
    assert listed.headers["content-type"] == "text/plain; charset=utf-8"


async def test_the_compressed_indexes_hold_the_same_list(client, hosted, root):
    await upload(client, root, make_deb())
    base = f"{DISTS}/main/binary-amd64/Packages"

    plain = (await client.get(base, headers=root)).content
    packed = await client.get(f"{base}.gz", headers=root)
    xz = await client.get(f"{base}.xz", headers=root)

    assert gzip.decompress(packed.content) == plain
    assert lzma.decompress(xz.content) == plain
    assert packed.headers["content-type"] == "application/gzip"


async def test_a_package_for_all_architectures_is_listed_for_each(client, hosted, root):
    await upload(client, root, make_deb())
    await upload(
        client, root, make_deb(control_text(package="megooarti-tool", architecture="arm64"))
    )

    arm = await client.get(f"{DISTS}/main/binary-arm64/Packages", headers=root)
    amd = await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)

    assert [control.get(p, "Package") for p in paragraphs(arm.content)] == [
        "megooarti-hello",
        "megooarti-tool",
    ]
    assert amd.status_code == 404  # the repository has no amd64 package now


async def test_release_names_every_index_and_is_signed_with_the_repositorys_key(
    client, hosted, root
):
    await upload(client, root, make_deb())

    release = (await client.get(f"{DISTS}/Release", headers=root)).content
    inline = (await client.get(f"{DISTS}/InRelease", headers=root)).content
    detached = await client.get(f"{DISTS}/Release.gpg", headers=root)
    key = (await client.get(f"{URL}/public.key", headers=root)).content

    assert release.startswith(b"Origin: MegooArti\nLabel: apt-hosted\nSuite: stable\n")
    assert verified(inline, key) == release.removesuffix(b"\n")
    assert verified(release, key, detached.content) == release
    assert detached.headers["content-type"] == "application/pgp-signature"
    packages = (await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)).content
    assert f" {hashlib.sha256(packages).hexdigest()} " in release.decode()


async def test_an_empty_repository_has_signed_empty_indexes(client, hosted, root):
    release = await client.get(f"{DISTS}/InRelease", headers=root)
    empty = await client.get(f"{DISTS}/main/binary-arm64/Packages", headers=root)

    assert release.status_code == 200
    assert b"Architectures: amd64 arm64\n" in release.content
    assert (empty.status_code, empty.content) == (200, b"")


async def test_the_public_key_is_the_one_the_api_shows(admin_client, hosted):
    shown = (await admin_client.get("/api/v1/repositories/apt-hosted/signing-key")).json()

    served = await admin_client.get(f"{URL}/public.key")

    assert served.text == shown["public_key"]
    assert served.headers["content-type"] == "application/pgp-keys"


async def test_a_new_key_signs_the_indexes_from_then_on(admin_client, hosted):
    before = (await admin_client.get(f"{DISTS}/InRelease")).content

    await admin_client.post("/api/v1/repositories/apt-hosted/signing-key/generate", json={})

    key = (await admin_client.get(f"{URL}/public.key")).content
    after = (await admin_client.get(f"{DISTS}/InRelease")).content
    verified(after, key)
    with pytest.raises(RuntimeError):
        verified(before, key)


async def test_a_deleted_package_leaves_the_indexes(client, hosted, root):
    await upload(client, root, make_deb())
    await upload(client, root, make_deb(control_text(version="2.0")))

    deleted = await client.delete(f"{URL}/{HELLO}", headers=root)
    listed = await client.get(f"{DISTS}/main/binary-amd64/Packages", headers=root)

    assert deleted.status_code == 204
    assert [control.get(p, "Version") for p in paragraphs(listed.content)] == ["2.0"]
    assert (await client.delete(f"{URL}/{HELLO}", headers=root)).status_code == 404


async def test_the_indexes_are_written_once_for_each_revision(client, hosted, root, monkeypatch):
    written = []
    write = apt_format._written

    def counted(*arguments):
        written.append(1)
        return write(*arguments)

    monkeypatch.setattr(apt_format, "_written", counted)

    await client.get(f"{DISTS}/InRelease", headers=root)
    await client.get(f"{DISTS}/main/binary-amd64/Packages.xz", headers=root)
    assert len(written) == 1
    await upload(client, root, make_deb())
    await client.get(f"{DISTS}/InRelease", headers=root)
    assert len(written) == 2


async def test_an_index_a_client_has_is_not_sent_again(client, hosted, root):
    first = await client.get(f"{DISTS}/InRelease", headers=root)

    again = await client.get(
        f"{DISTS}/InRelease", headers={**root, "If-None-Match": first.headers["etag"]}
    )

    assert again.status_code == 304


@pytest.mark.parametrize(
    "path",
    [
        "dists/bookworm/InRelease",
        "dists/stable/contrib/binary-amd64/Packages",
        "dists/stable/main/i18n/Translation-en",
        "dists/stable/main/binary-amd64/Packages.bz2",
        "README",
    ],
)
async def test_what_the_repository_does_not_have_is_not_found(client, hosted, root, path):
    assert (await client.get(f"{URL}/{path}", headers=root)).status_code == 404


async def test_a_repository_is_read_with_the_right_to_read(client, db, hosted, make_user):
    await roles.create_role(db, "readers", "", ["repository:apt:apt-hosted:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    assert (await client.get(f"{DISTS}/InRelease")).status_code == 401
    assert (
        await client.get(f"{DISTS}/InRelease", headers=basic("rae", PASSWORD))
    ).status_code == 200
    assert (
        await client.get(f"{URL}/public.key", headers=basic("rae", PASSWORD))
    ).status_code == 200


async def test_a_key_that_cannot_be_read_is_said_to_be_so(
    client, hosted, root, settings, monkeypatch
):
    await client.get(f"{URL}/public.key", headers=root)  # the key is made
    monkeypatch.setattr(settings, "secret_key", "another installation's key")
    from megooarti.secrets_box import forget_keys

    forget_keys()
    try:
        response = await client.get(f"{DISTS}/InRelease", headers=root)
    finally:
        forget_keys()

    assert (response.status_code, error_code(response)) == (500, "signing_key_unreadable")


async def test_a_suite_is_chosen_when_the_repository_is_made_and_kept(admin_client):
    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apt-hosted",
            "format": "apt",
            "type": "hosted",
            "format_config": {"suite": "trixie"},
        },
    )
    changed = await admin_client.put(
        "/api/v1/repositories/apt-hosted", json={"format_config": {"suite": "forky"}}
    )
    kept = await admin_client.put("/api/v1/repositories/apt-hosted", json={"format_config": {}})

    assert made.json()["format_config"] == {"suite": "trixie"}
    assert (changed.status_code, changed.json()["error"]["details"][0]["field"]) == (
        422,
        "format_config.suite",
    )
    assert kept.json()["format_config"] == {"suite": "trixie"}
    assert (await admin_client.get(f"{URL}/dists/trixie/InRelease")).status_code == 200


@pytest.mark.parametrize(
    ("type", "format_config", "field"),
    [
        ("hosted", {"suite": "a/b"}, "format_config.suite"),
        ("hosted", {"suite": ""}, "format_config.suite"),
        ("hosted", {"component": "main"}, "format_config.component"),
        ("proxy", {"suite": "stable"}, "format_config"),
        ("group", {}, "type"),
    ],
)
async def test_settings_that_cannot_be_used_are_refused(admin_client, type, format_config, field):
    body = {"name": "apt", "format": "apt", "type": type, "format_config": format_config}
    if type == "proxy":
        body["proxy"] = {"remote_url": "http://deb.debian.org/debian"}

    refused = await admin_client.post("/api/v1/repositories", json=body)

    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["field"] == field
