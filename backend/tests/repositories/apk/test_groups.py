"""A group of apk repositories: one address and one key for its members' indexes."""

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from megooarti.repositories import signing
from megooarti.repositories.apk import groups as apk_groups
from megooarti.repositories.apk import index
from tests.accounts import error_code
from tests.repositories.apk.conftest import (
    REMOTE,
    ROOT,
    create,
    mirror_files,
    mirror_key,
    upload,
    written_behind,
)
from tests.repositories.apk.packages import DATA, REAL, make_apk, pkginfo

GROUP = "/repository/apk-public"
X86 = "v3.24/main/x86_64"
KEY = "megooarti-apk-public.rsa.pub"
HELLO = "megooarti-hello-1.0-r0.apk"
OURS = make_apk()
THEIRS = make_apk(pkginfo(description="The mirror's own"))
# The mirror's packages: one an earlier member has too, and one of its own.
MIRRORED = {HELLO: THEIRS, REAL[1]: (DATA / REAL[1]).read_bytes()}


def opened(data: bytes, public_key: bytes) -> index.Read:
    """An index, its signature checked with one public key. Raises if it does not hold."""
    read = index.read(data)
    key = serialization.load_pem_public_key(public_key)
    key.verify(read.signature, read.packed, padding.PKCS1v15(), hashes.SHA1())
    return read


def names(read: index.Read) -> list[tuple[str, str]]:
    found = []
    for record in read.text.split("\n\n"):
        said = dict(line.split(":", 1) for line in record.splitlines() if line[1:2] == ":")
        if said:
            found.append((said["P"], said["T"]))
    return found


@pytest.fixture
async def mirror(fake_remote):
    """A mirror whose x86_64 directory has two packages, its index signed by its key."""
    fake_remote.files.update(await mirror_files(X86, MIRRORED))
    return fake_remote


async def a_proxy(db, keys: str | None = None):
    return await create(
        db,
        "apk-alpine",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
        format_config={"remote_keys": mirror_key().public_key if keys is None else keys},
    )


async def a_group(db, *members: str):
    return await create(db, "apk-public", type="group", group={"members": list(members)})


async def group_index(client, root, directory: str = X86) -> index.Read:
    data = (await client.get(f"{GROUP}/{directory}/APKINDEX.tar.gz", headers=root)).content
    key = (await client.get(f"{GROUP}/{KEY}", headers=root)).content
    return opened(data, key)


async def test_a_directory_one_member_has_is_its_index_signed_again_with_the_groups_key(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"v3.23/main/x86_64/{HELLO}", OURS)

    ours = await group_index(client, root, "v3.23/main/x86_64")
    theirs = await group_index(client, root)

    hosted = index.read(
        (
            await client.get(
                f"/repository/apk-hosted/v3.23/main/x86_64/{index.INDEX}", headers=root
            )
        ).content
    )
    mirrored = index.read(mirror.files[f"{ROOT}/{X86}/{index.INDEX}"])
    assert (ours.packed, ours.key_name) == (hosted.packed, KEY)
    assert (theirs.packed, theirs.key_name) == (mirrored.packed, KEY)


async def test_a_directory_several_members_have_is_merged_an_earlier_members_package_first(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    merged = await group_index(client, root)

    assert names(merged) == [("megooarti-hello", "Says hello"), ("yash-binsh", "yash as /bin/sh")]


async def test_a_package_comes_from_the_first_member_that_has_it(client, db, root, mirror):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    ours = await client.get(f"{GROUP}/{X86}/{HELLO}", headers=root)
    theirs = await client.get(f"{GROUP}/{X86}/{REAL[1]}", headers=root)

    assert ours.content == OURS
    assert theirs.content == MIRRORED[REAL[1]]


async def test_a_proxy_whose_index_its_keys_did_not_sign_is_left_out(client, db, root, fake_remote):
    another = signing.generate_rsa()
    fake_remote.files.update(await mirror_files(X86, MIRRORED, key=another))
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    merged = await group_index(client, root)
    shown = (await client.get("/api/v1/repositories/apk-alpine", headers=root)).json()

    assert [name for name, _ in names(merged)] == ["megooarti-hello"]
    assert shown["status"]["last_error"].startswith("Left out of the group apk-public:")
    assert "not signed by its remote's keys" in shown["status"]["last_error"]


async def test_a_proxy_without_its_remotes_keys_cannot_be_a_member(admin_client):
    for body in (
        {"name": "apk-hosted", "format": "apk", "type": "hosted"},
        {"name": "apk-alpine", "format": "apk", "type": "proxy", "proxy": {"remote_url": REMOTE}},
    ):
        assert (await admin_client.post("/api/v1/repositories", json=body)).status_code == 201

    refused = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apk-public",
            "format": "apk",
            "type": "group",
            "group": {"members": ["apk-hosted", "apk-alpine"]},
        },
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "group.members"


async def test_the_merged_index_is_written_once_for_each_state_of_the_members(
    client, db, root, mirror, monkeypatch
):
    written = []
    write = apk_groups._written

    def counted(*arguments):
        written.append(1)
        return write(*arguments)

    monkeypatch.setattr(apk_groups, "_written", counted)
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)

    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    assert len(written) == 1
    await upload(
        client, root, f"{X86}/megooarti-tool-1.0-r0.apk", make_apk(pkginfo(name="megooarti-tool"))
    )
    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)  # written again, behind
    await written_behind()
    assert len(written) == 2
    again = await group_index(client, root)
    assert "megooarti-tool" in [name for name, _ in names(again)]


async def test_while_a_member_it_had_cannot_be_checked_the_last_whole_index_is_kept(
    client, db, root, mirror, monkeypatch
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")
    await upload(client, root, f"{X86}/{HELLO}", OURS)
    whole = (await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)).content
    good = mirror.files[f"{ROOT}/{X86}/{index.INDEX}"]
    mirror.files[f"{ROOT}/{X86}/{index.INDEX}"] = b"not an index"

    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await written_behind()
    held = (await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)).content
    mirror.files[f"{ROOT}/{X86}/{index.INDEX}"] = good
    monkeypatch.setattr(apk_groups, "RETRY", timedelta(0))
    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await written_behind()
    again = await group_index(client, root)

    assert held == whole
    assert "yash-binsh" in [name for name, _ in names(again)]


async def test_a_member_added_that_cannot_be_checked_does_not_keep_the_others_still(
    client, db, root, fake_remote
):
    fake_remote.files.update(await mirror_files(X86, MIRRORED, key=signing.generate_rsa()))
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted")
    await upload(client, root, f"{X86}/{HELLO}", OURS)
    await group_index(client, root)
    changed = await client.put(
        "/api/v1/repositories/apk-public",
        json={"group": {"members": ["apk-hosted", "apk-alpine"]}},
        headers=root,
    )
    assert changed.status_code == 200, changed.text
    await upload(
        client, root, f"{X86}/megooarti-tool-1.0-r0.apk", make_apk(pkginfo(name="megooarti-tool"))
    )

    await client.get(f"{GROUP}/{X86}/APKINDEX.tar.gz", headers=root)
    await written_behind()
    found = await group_index(client, root)

    assert [name for name, _ in names(found)] == ["megooarti-hello", "megooarti-tool"]


async def test_a_hosted_member_without_packages_adds_nothing_to_a_mirrors_directory(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "apk-hosted", "apk-alpine")

    found = await group_index(client, root)

    assert found.packed == index.read(mirror.files[f"{ROOT}/{X86}/{index.INDEX}"]).packed


async def test_a_group_of_members_without_packages_has_an_empty_index(client, db, root):
    await create(db)
    await a_group(db, "apk-hosted")

    found = await group_index(client, root, "v3.24/main/riscv64")

    assert found.text == ""


async def test_a_proxys_remote_keys_are_kept_and_shown(admin_client):
    keys = mirror_key().public_key + (DATA / "builder-6ad0887f.rsa.pub").read_text(encoding="utf-8")

    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apk-alpine",
            "format": "apk",
            "type": "proxy",
            "proxy": {"remote_url": REMOTE},
            "format_config": {"remote_keys": keys},
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["format_config"] == {"remote_keys": keys}


@pytest.mark.parametrize(
    ("keys", "said"),
    [
        ("not a key", "not one or more RSA public keys"),
        (mirror_key().private_key, "private key"),
        (
            (DATA.parent.parent / "apt/data/plain-rsa.pub.asc").read_text(encoding="utf-8"),
            "not one",
        ),
    ],
)
async def test_keys_apk_cannot_check_with_are_refused(admin_client, keys, said):
    refused = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apk-alpine",
            "format": "apk",
            "type": "proxy",
            "proxy": {"remote_url": REMOTE},
            "format_config": {"remote_keys": keys},
        },
    )

    assert refused.status_code == 422
    detail = refused.json()["error"]["details"][0]
    assert detail["field"] == "format_config.remote_keys"
    assert said in detail["message"]
