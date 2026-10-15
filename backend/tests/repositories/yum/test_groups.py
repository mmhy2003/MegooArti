"""A group of YUM repositories: one address and one key for its members' `repodata/`."""

import gzip
import re
from datetime import timedelta
from xml.etree import ElementTree

import pysequoia
import pytest
import zstandard

from megooarti.repositories import signing
from megooarti.repositories.yum import groups as yum_groups
from tests.accounts import error_code
from tests.repositories.yum.conftest import (
    COMPS,
    REMOTE,
    ROOT,
    create,
    mirror_files,
    mirror_key,
    upload,
    written_behind,
)
from tests.repositories.yum.packages import make_rpm

GROUP = "/repository/yum-public"
COMMON = "{http://linux.duke.edu/metadata/common}"
REPO = "{http://linux.duke.edu/metadata/repo}"
# The mirror's packages: one an earlier member holds the path of with another package,
# one an earlier member has too, and one of its own.
COLLIDING = "Packages/h/megooarti-hello-2.0-1.noarch.rpm"
SHARED = "Packages/b/bash-5.3-1.x86_64.rpm"
ITS_OWN = "Packages/m/megooarti-tool-0.3-1.x86_64.rpm"
MIRRORED = {
    COLLIDING: make_rpm(version="2.0"),
    SHARED: make_rpm("bash", "5.3", "1", "x86_64"),
    ITS_OWN: make_rpm("megooarti-tool", "0.3", "1", "x86_64"),
}


def verified(data: bytes, signature: bytes, public_key: bytes) -> bytes:
    """What a detached signature vouches for, checked with one public key. Raises if not."""
    signing.verify_detached(data, signature, [pysequoia.Cert.from_bytes(public_key)])
    return data


def unpacked(href: str, data: bytes) -> bytes:
    if href.endswith(".zst"):
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)
    return gzip.decompress(data)


async def metadata(client, headers, base: str) -> dict[str, bytes]:
    """A `repomd.xml`, and each file it names, unpacked where packed, by its type."""
    repomd = await client.get(f"{base}/repodata/repomd.xml", headers=headers)
    assert repomd.status_code == 200, repomd.text
    found = {"repomd": repomd.content}
    for data in ElementTree.fromstring(repomd.content).iter(f"{REPO}data"):
        href = data.find(f"{REPO}location").get("href")
        got = await client.get(f"{base}/{href}", headers=headers)
        assert got.status_code == 200, href
        found[data.get("type")] = (
            got.content if href.endswith(".xml") else unpacked(href, got.content)
        )
    return found


def locations(primary: bytes) -> list[str]:
    return [p.find(f"{COMMON}location").get("href") for p in ElementTree.fromstring(primary)]


@pytest.fixture
async def mirror(fake_remote):
    """A mirror with three packages and package groups; its repomd.xml is not signed."""
    fake_remote.files.update(await mirror_files(MIRRORED))
    return fake_remote


async def a_proxy(db, keys: str | None = None):
    return await create(
        db,
        "yum-fedora",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
        format_config={"remote_keys": keys} if keys else None,
    )


async def a_group(db, *members: str):
    return await create(db, "yum-public", type="group", group={"members": list(members)})


async def ours(client, root) -> None:
    """The hosted member's packages: one at a path the mirror has another at, and one
    the mirror has as well."""
    await upload(client, root, "megooarti-hello-1.0-1.noarch.rpm", make_rpm())
    await upload(client, root, COLLIDING, make_rpm("megooarti-other"))
    await upload(client, root, "bash.rpm", make_rpm("bash", "5.3", "1", "x86_64", summary="ours"))


async def test_a_directory_one_member_has_is_its_repomd_signed_with_the_groups_key(
    client, db, root, mirror
):
    await create(db, format_config={"repodata_depth": 2})
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "el10/x86_64/a.rpm", make_rpm())

    key = (await client.get(f"{GROUP}/public.key", headers=root)).content
    hosted = (
        await client.get("/repository/yum-hosted/el10/x86_64/repodata/repomd.xml", headers=root)
    ).content
    for base, original in (
        (f"{GROUP}/el10/x86_64", hosted),
        (GROUP, mirror.files[f"{ROOT}/repodata/repomd.xml"]),
    ):
        repomd = (await client.get(f"{base}/repodata/repomd.xml", headers=root)).content
        signature = (await client.get(f"{base}/repodata/repomd.xml.asc", headers=root)).content
        assert verified(repomd, signature, key) == original
    hosted_key = (await client.get("/repository/yum-hosted/public.key", headers=root)).content
    assert key != hosted_key


async def test_every_other_file_of_such_a_directory_comes_from_that_member(
    client, db, root, mirror
):
    await a_proxy(db)
    await a_group(db, "yum-fedora")

    found = await metadata(client, root, GROUP)

    assert sorted(locations(found["primary"])) == sorted(MIRRORED)
    assert found["group"] == COMPS


async def test_a_directory_several_members_have_is_merged_an_earlier_members_package_first(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await ours(client, root)

    found = await metadata(client, root, GROUP)

    assert locations(found["primary"]) == [
        COLLIDING,  # ours: megooarti-other, which the mirror's hello cannot take the place of
        "bash.rpm",  # ours, which the mirror has too
        "megooarti-hello-1.0-1.noarch.rpm",
        ITS_OWN,  # the mirror's own
    ]
    for kind in ("filelists", "other"):
        tree = ElementTree.fromstring(found[kind])
        assert [package.get("name") for package in tree] == [
            "megooarti-other",
            "bash",
            "megooarti-hello",
            "megooarti-tool",
        ]
    assert found["group"] == COMPS  # the mirror's, the first member that has them
    hrefs = re.findall(rb'href="(repodata/[^"]+)"', found["repomd"])
    assert [href.rsplit(b".", 1)[1] for href in hrefs] == [b"zst", b"zst", b"zst", b"xml"]


async def test_a_package_comes_from_the_first_member_that_has_its_path(client, db, root, mirror):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await ours(client, root)

    theirs = await client.get(f"{GROUP}/{ITS_OWN}", headers=root)
    mine = await client.get(f"{GROUP}/{COLLIDING}", headers=root)

    assert theirs.content == MIRRORED[ITS_OWN]
    assert mine.content == make_rpm("megooarti-other")


async def test_a_member_whose_file_is_not_the_one_its_repomd_names_is_left_out(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())
    primary = next(path for path in mirror.files if path.endswith("-primary.xml.gz"))
    mirror.files[primary] = gzip.compress(b"<metadata/>", mtime=0)

    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    # Until the proxy next reaches its remote, as the group's next request has it do.
    shown = (await client.get("/api/v1/repositories/yum-fedora", headers=root)).json()
    found = await metadata(client, root, GROUP)

    assert locations(found["primary"]) == ["a.rpm"]
    assert shown["status"]["last_error"].startswith("Left out of the group yum-public:")
    assert "not the one its repomd.xml names" in shown["status"]["last_error"]


@pytest.mark.parametrize(
    ("signer", "kept"),
    [("mirror", True), (None, False), ("another", False)],
)
async def test_a_proxy_given_its_remotes_keys_is_kept_only_if_they_signed_its_repomd(
    client, db, root, fake_remote, signer, kept
):
    key = {"mirror": mirror_key(), "another": signing.generate_openpgp("Another"), None: None}
    fake_remote.files.update(await mirror_files(MIRRORED, key=key[signer]))
    await create(db)
    await a_proxy(db, keys=mirror_key().public_key)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())

    found = await metadata(client, root, GROUP)

    assert (ITS_OWN in locations(found["primary"])) is kept


async def test_the_merged_metadata_is_written_once_for_each_state_of_the_members(
    client, db, root, mirror, monkeypatch
):
    written = []
    write = yum_groups._written

    async def counted(*arguments):
        written.append(1)
        return await write(*arguments)

    monkeypatch.setattr(yum_groups, "_written", counted)
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())

    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    await client.get(f"{GROUP}/repodata/repomd.xml.asc", headers=root)
    assert len(written) == 1
    await upload(client, root, "b.rpm", make_rpm(version="2.0"))
    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)  # written again, behind
    await written_behind()
    assert len(written) == 2
    again = await metadata(client, root, GROUP)
    assert "b.rpm" in locations(again["primary"])


async def test_while_a_member_cannot_be_checked_the_last_whole_metadata_is_kept(
    client, db, root, mirror, monkeypatch
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")
    await upload(client, root, "a.rpm", make_rpm())
    whole = (await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)).content
    good = mirror.files[f"{ROOT}/repodata/repomd.xml"]
    mirror.files[f"{ROOT}/repodata/repomd.xml"] = b"not xml"

    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    await written_behind()
    held = (await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)).content
    mirror.files[f"{ROOT}/repodata/repomd.xml"] = good
    monkeypatch.setattr(yum_groups, "RETRY", timedelta(0))
    await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)
    await written_behind()
    again = await metadata(client, root, GROUP)

    assert held == whole
    assert ITS_OWN in locations(again["primary"])


async def test_a_hosted_member_without_packages_adds_nothing_to_a_mirrors_directory(
    client, db, root, mirror
):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")

    repomd = (await client.get(f"{GROUP}/repodata/repomd.xml", headers=root)).content

    assert repomd == mirror.files[f"{ROOT}/repodata/repomd.xml"]


async def test_a_group_of_members_without_packages_has_empty_metadata(client, db, root):
    await create(db)
    await a_group(db, "yum-hosted")

    found = await metadata(client, root, GROUP)

    assert locations(found["primary"]) == []


@pytest.mark.parametrize("path", ["el9/repodata/repomd.xml", "repodata/primary.xml.gz"])
async def test_what_no_member_has_is_not_found(client, db, root, mirror, path):
    await create(db)
    await a_proxy(db)
    await a_group(db, "yum-hosted", "yum-fedora")

    assert (await client.get(f"{GROUP}/{path}", headers=root)).status_code == 404


async def test_a_proxys_remote_keys_are_kept_and_shown(admin_client):
    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "yum-rocky",
            "format": "yum",
            "type": "proxy",
            "proxy": {"remote_url": "http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os"},
            "format_config": {"remote_keys": mirror_key().public_key},
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["format_config"] == {"remote_keys": mirror_key().public_key}


@pytest.mark.parametrize(
    ("type", "format_config", "field"),
    [
        ("proxy", {"remote_keys": "not a key"}, "format_config.remote_keys"),
        ("proxy", {"suite": "x"}, "format_config.suite"),
        ("group", {"repodata_depth": 1}, "format_config"),
    ],
)
async def test_settings_a_proxy_or_group_cannot_use_are_refused(
    admin_client, type, format_config, field
):
    body = {"name": "yum", "format": "yum", "type": type, "format_config": format_config}
    if type == "proxy":
        body["proxy"] = {"remote_url": REMOTE}
    else:
        body["group"] = {"members": []}

    refused = await admin_client.post("/api/v1/repositories", json=body)

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field
