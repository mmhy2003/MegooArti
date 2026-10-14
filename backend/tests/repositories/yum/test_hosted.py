"""A hosted YUM repository, as dnf and an uploader use it."""

import gzip
import re
from xml.etree import ElementTree

import pysequoia
import pytest

from megooarti.repositories.yum import format as yum_format
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.yum.conftest import URL, create, upload
from tests.repositories.yum.packages import DATA, HELLO, SOURCE, TOOL, make_rpm

REPO = "{http://linux.duke.edu/metadata/repo}"
COMMON = "{http://linux.duke.edu/metadata/common}"


def verified(data: bytes, public_key: bytes, signature: bytes) -> bytes:
    """What a detached signature vouches for, checked with a public key. Raises if it does not."""
    certificate = pysequoia.Cert.from_bytes(public_key)
    pysequoia.verify(
        bytes=data, store=lambda _: [certificate], signature=pysequoia.Sig.from_bytes(signature)
    )
    return data


async def metadata(client, headers, directory: str = "") -> dict[str, bytes]:
    """A directory's `repomd.xml`, and each file it names, unpacked, by its type."""
    base = f"{URL}/{directory}/repodata" if directory else f"{URL}/repodata"
    repomd = await client.get(f"{base}/repomd.xml", headers=headers)
    assert repomd.status_code == 200, repomd.text
    found = {"repomd": repomd.content}
    for data in ElementTree.fromstring(repomd.content).iter(f"{REPO}data"):
        href = data.find(f"{REPO}location").get("href")
        packed = await client.get(f"{base}/{href.removeprefix('repodata/')}", headers=headers)
        assert packed.status_code == 200, href
        found[data.get("type")] = gzip.decompress(packed.content)
    return found


def locations(primary: bytes) -> list[str]:
    tree = ElementTree.fromstring(primary)
    return [package.find(f"{COMMON}location").get("href") for package in tree]


async def test_a_package_put_to_its_path_is_kept_there(client, hosted, root):
    package = (DATA / HELLO).read_bytes()

    response = await upload(client, root, f"Packages/{HELLO}", package)
    fetched = await client.get(f"{URL}/Packages/{HELLO}", headers=root)

    assert response.status_code == 201, response.text
    assert fetched.content == package
    assert fetched.headers["content-type"] == "application/x-rpm"


async def test_a_package_put_again_replaces_it_as_the_policy_allows(client, db, root):
    await create(db, "yum-hosted")
    await create(db, "yum-releases", hosted={"deployment_policy": "disable_redeploy"})

    assert (await upload(client, root, "a.rpm", make_rpm())).status_code == 201
    assert (await upload(client, root, "a.rpm", make_rpm())).status_code == 204
    assert (
        await upload(client, root, "a.rpm", make_rpm(), repository="yum-releases")
    ).status_code == 201
    again = await upload(client, root, "a.rpm", make_rpm(), repository="yum-releases")
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")


@pytest.mark.parametrize(
    ("package", "reason"),
    [
        (b"PK\x03\x04 a zip file" + b"\0" * 100, "not an RPM"),
        ((DATA / SOURCE).read_bytes(), "source RPM"),
    ],
)
async def test_what_is_not_an_rpm_dnf_installs_is_refused_and_nothing_is_kept(
    client, hosted, root, settings, package, reason
):
    response = await upload(client, root, "a.rpm", package)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert reason in response.json()["error"]["message"]
    store = settings.data_dir / "blobs" / "default"
    assert [path for path in store.rglob("*") if path.is_file()] == []


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("notes.txt", 400, "invalid_path"),
        ("repodata/repomd.xml", 405, "method_not_allowed"),
        ("repodata/a.rpm", 405, "method_not_allowed"),
        ("public.key", 405, "method_not_allowed"),
    ],
)
async def test_a_package_is_put_only_where_a_package_can_be(
    client, hosted, root, path, status, code
):
    response = await upload(client, root, path, make_rpm())

    assert (response.status_code, error_code(response)) == (status, code)


async def test_an_upload_needs_credentials_and_the_right_to_add(client, db, hosted, make_user):
    await roles.create_role(db, "readers", "", ["repository:yum:yum-hosted:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    nobody = await upload(client, {}, "a.rpm", make_rpm())
    reader = await upload(client, basic("rae", PASSWORD), "a.rpm", make_rpm())

    assert nobody.status_code == 401
    assert reader.status_code == 403


async def test_repomd_names_the_packages_and_is_signed_with_the_repositorys_key(
    client, hosted, root
):
    await upload(client, root, HELLO, (DATA / HELLO).read_bytes())
    await upload(client, root, f"tools/{TOOL}", (DATA / TOOL).read_bytes())

    found = await metadata(client, root)
    signature = await client.get(f"{URL}/repodata/repomd.xml.asc", headers=root)
    key = (await client.get(f"{URL}/public.key", headers=root)).content

    assert locations(found["primary"]) == [HELLO, f"tools/{TOOL}"]
    assert b'name="megooarti-tool" arch="x86_64"' in found["filelists"]
    assert b"- Change 12 &amp; more" in found["other"]
    assert verified(found["repomd"], key, signature.content) == found["repomd"]
    assert signature.headers["content-type"] == "application/pgp-signature"
    assert key.startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----")


async def test_an_empty_repository_has_signed_empty_metadata(client, hosted, root):
    found = await metadata(client, root)
    signature = await client.get(f"{URL}/repodata/repomd.xml.asc", headers=root)

    assert b'packages="0"' in found["primary"]
    assert signature.status_code == 200


async def test_at_depth_2_each_directory_two_down_lists_the_packages_under_it(client, db, root):
    await create(db, format_config={"repodata_depth": 2})
    for path in (f"el9/x86_64/{HELLO}", f"el9/x86_64/Packages/t/{TOOL}", f"el10/x86_64/{HELLO}"):
        assert (
            await upload(client, root, path, (DATA / path.rpartition("/")[2]).read_bytes())
        ).status_code == 201

    el9 = await metadata(client, root, "el9/x86_64")
    el10 = await metadata(client, root, "el10/x86_64")
    nothing = await metadata(client, root, "el8/x86_64")

    assert locations(el9["primary"]) == [f"Packages/t/{TOOL}", HELLO]  # by path
    assert locations(el10["primary"]) == [HELLO]
    assert locations(nothing["primary"]) == []
    for shallow in ("repodata/repomd.xml", "el9/repodata/repomd.xml", "a/b/c/repodata/repomd.xml"):
        assert (await client.get(f"{URL}/{shallow}", headers=root)).status_code == 404


async def test_a_package_not_as_deep_as_the_metadata_is_refused(client, db, root):
    await create(db, format_config={"repodata_depth": 2})

    response = await upload(client, root, f"el9/{HELLO}", make_rpm())

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert "repodata_depth" in response.json()["error"]["message"]


async def test_the_files_the_last_repomd_named_are_still_served(client, hosted, root):
    """A client that read `repomd.xml` a moment before a change still gets what it named."""
    await upload(client, root, "a.rpm", make_rpm())
    first = (await client.get(f"{URL}/repodata/repomd.xml", headers=root)).text
    await upload(client, root, "b.rpm", make_rpm(version="2.0"))
    second = (await client.get(f"{URL}/repodata/repomd.xml", headers=root)).text
    await upload(client, root, "c.rpm", make_rpm(version="3.0"))
    await client.get(f"{URL}/repodata/repomd.xml", headers=root)

    named = re.findall(r'href="(repodata/[^"]+)"', first)
    then = re.findall(r'href="(repodata/[^"]+)"', second)
    assert set(named).isdisjoint(then)
    for href in then:
        assert (await client.get(f"{URL}/{href}", headers=root)).status_code == 200
    for href in named:
        assert (await client.get(f"{URL}/{href}", headers=root)).status_code == 404


async def test_metadata_is_written_once_for_each_revision(client, hosted, root, monkeypatch):
    written = []
    write = yum_format._written

    def counted(*arguments):
        written.append(1)
        return write(*arguments)

    monkeypatch.setattr(yum_format, "_written", counted)

    await client.get(f"{URL}/repodata/repomd.xml", headers=root)
    await client.get(f"{URL}/repodata/repomd.xml.asc", headers=root)
    assert len(written) == 1
    await upload(client, root, "a.rpm", make_rpm())
    await client.get(f"{URL}/repodata/repomd.xml", headers=root)
    assert len(written) == 2


async def test_repomd_is_sent_again_whatever_date_a_client_has_unless_it_has_these_bytes(
    client, hosted, root
):
    """Two changes in one second share a date: only the content says whether it changed."""
    await upload(client, root, "a.rpm", make_rpm())
    before = await client.get(f"{URL}/repodata/repomd.xml", headers=root)
    await upload(client, root, "b.rpm", make_rpm(version="2.0"))
    later = {"If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"}

    after = await client.get(f"{URL}/repodata/repomd.xml", headers={**root, **later})
    same = await client.get(
        f"{URL}/repodata/repomd.xml", headers={**root, "If-None-Match": after.headers["etag"]}
    )

    assert after.status_code == 200 and after.content != before.content
    assert after.headers["content-type"] == "application/xml"
    assert same.status_code == 304


async def test_a_deleted_package_leaves_the_metadata(client, hosted, root):
    await upload(client, root, "a.rpm", make_rpm())
    await upload(client, root, "b.rpm", make_rpm(version="2.0"))

    deleted = await client.delete(f"{URL}/a.rpm", headers=root)
    found = await metadata(client, root)

    assert deleted.status_code == 204
    assert locations(found["primary"]) == ["b.rpm"]
    assert (await client.delete(f"{URL}/a.rpm", headers=root)).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "repodata/primary.xml.gz",
        f"repodata/{'0' * 64}-primary.xml.gz",
        "repodata/comps.xml",
        "README",
        "a.rpm",
    ],
)
async def test_what_the_repository_does_not_have_is_not_found(client, hosted, root, path):
    assert (await client.get(f"{URL}/{path}", headers=root)).status_code == 404


async def test_a_repository_is_read_with_the_right_to_read(client, db, hosted, make_user):
    await roles.create_role(db, "readers", "", ["repository:yum:yum-hosted:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    assert (await client.get(f"{URL}/repodata/repomd.xml")).status_code == 401
    for path in ("repodata/repomd.xml", "repodata/repomd.xml.asc", "public.key"):
        response = await client.get(f"{URL}/{path}", headers=basic("rae", PASSWORD))
        assert response.status_code == 200, path


async def test_the_depth_is_chosen_when_the_repository_is_made_and_kept(admin_client):
    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "yum-hosted",
            "format": "yum",
            "type": "hosted",
            "format_config": {"repodata_depth": 2},
        },
    )
    changed = await admin_client.put(
        "/api/v1/repositories/yum-hosted", json={"format_config": {"repodata_depth": 1}}
    )
    kept = await admin_client.put("/api/v1/repositories/yum-hosted", json={"format_config": {}})
    default = await admin_client.post(
        "/api/v1/repositories", json={"name": "yum-flat", "format": "yum", "type": "hosted"}
    )

    assert made.json()["format_config"] == {"repodata_depth": 2}
    assert (changed.status_code, changed.json()["error"]["details"][0]["field"]) == (
        422,
        "format_config.repodata_depth",
    )
    assert kept.json()["format_config"] == {"repodata_depth": 2}
    assert default.json()["format_config"] == {"repodata_depth": 0}


@pytest.mark.parametrize(
    ("type", "format_config", "field"),
    [
        ("hosted", {"repodata_depth": 6}, "format_config.repodata_depth"),
        ("hosted", {"repodata_depth": -1}, "format_config.repodata_depth"),
        ("hosted", {"repodata_depth": "2"}, "format_config.repodata_depth"),
        ("hosted", {"repodata_depth": True}, "format_config.repodata_depth"),
        ("hosted", {"suite": "stable"}, "format_config.suite"),
        ("proxy", {"repodata_depth": 1}, "format_config"),
    ],
)
async def test_settings_that_cannot_be_used_are_refused(admin_client, type, format_config, field):
    body = {"name": "yum", "format": "yum", "type": type, "format_config": format_config}
    if type == "proxy":
        body["proxy"] = {"remote_url": "https://dl.fedoraproject.org/pub/fedora/linux"}

    refused = await admin_client.post("/api/v1/repositories", json=body)

    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_a_group_of_yum_repositories_is_not_made_yet(admin_client):
    refused = await admin_client.post(
        "/api/v1/repositories",
        json={"name": "yum-all", "format": "yum", "type": "group", "group": {"members": []}},
    )

    assert refused.status_code == 422


async def test_what_an_empty_directorys_repomd_named_is_served_after_its_first_package(
    client, db, root
):
    """A machine set up before the first upload may be between repomd.xml and its files."""
    await create(db, format_config={"repodata_depth": 1})
    empty = (await client.get(f"{URL}/el9/repodata/repomd.xml", headers=root)).text
    await upload(client, root, "el9/a.rpm", make_rpm())
    await client.get(f"{URL}/el9/repodata/repomd.xml", headers=root)

    for href in re.findall(r'href="(repodata/[^"]+)"', empty):
        assert (await client.get(f"{URL}/el9/{href}", headers=root)).status_code == 200, href
