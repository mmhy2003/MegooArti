"""A group of APT repositories: one address and one key for its members' suites."""

import asyncio
import gzip
import hashlib
import lzma
from datetime import UTC, datetime, timedelta

import pysequoia
import pytest

from megooarti.repositories import signing
from megooarti.repositories.apt import control, releases
from megooarti.repositories.apt import groups as apt_groups
from megooarti.repositories.content import RepositoryContext
from tests.accounts import error_code
from tests.repositories.apt.conftest import (
    MIRRORED_AT,
    REMOTE,
    create,
    mirror_files,
    mirror_key,
    paragraph,
    upload,
    written_behind,
)
from tests.repositories.apt.packages import control_text, make_deb

GROUP = "/repository/apt-public"
OURS = "pool/main/m/megooarti-hello/megooarti-hello_1.0-1_all.deb"


def verified(signed: bytes, public_key: bytes) -> bytes:
    """What a clear signature vouches for, checked with one public key. Raises if not."""
    certificate = pysequoia.Cert.from_bytes(public_key)
    return pysequoia.verify(bytes=signed, store=lambda _: [certificate]).bytes


def names(packages: bytes) -> list[tuple[str, str]]:
    found = []
    for part in packages.decode().split("\n\n"):
        if part.strip():
            said = control.parse(part)
            found.append((control.get(said, "Package"), control.get(said, "Filename")))
    return found


MIRRORED = paragraph("hello", "2.10-5") + paragraph("libc6", "2.41-6")


@pytest.fixture
def mirror(fake_remote):
    """A mirror whose trixie has two packages for amd64, signed by its key."""
    fake_remote.files.update(mirror_files("trixie", {"main/binary-amd64": MIRRORED}))
    fake_remote.files["debian/pool/main/h/hello/hello_2.10-5_amd64.deb"] = b"hello from the mirror"
    return fake_remote


async def a_proxy(db, keys: str | None = None):
    return await create(
        db,
        "apt-debian",
        type="proxy",
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
        format_config={"remote_keys": mirror_key().public_key if keys is None else keys},
    )


async def a_group(db, *members: str):
    return await create(db, "apt-public", type="group", group={"members": list(members)})


async def test_a_suite_one_member_has_is_its_release_signed_again_with_the_groups_key(
    client, db, root, mirror
):
    await create(db, "apt-hosted")
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    key = (await client.get(f"{GROUP}/public.key", headers=root)).content
    ours = (await client.get(f"{GROUP}/dists/stable/InRelease", headers=root)).content
    theirs = (await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)).content
    hosted = (await client.get("/repository/apt-hosted/dists/stable/Release", headers=root)).content

    mirrored = verified(
        mirror.files["debian/dists/trixie/InRelease"], mirror_key().public_key.encode()
    )
    for served, members in ((ours, hosted), (theirs, mirrored + b"\n")):
        release, original = releases.parse(verified(served, key)), releases.parse(members)
        assert (release.header, release.entries) == (original.header, original.entries)
        assert (release.components, release.architectures) == (
            original.components,
            original.architectures,
        )
        assert release.by_hash is original.by_hash


async def test_every_other_file_of_such_a_suite_comes_from_that_member(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    theirs = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.xz", headers=root)
    ours = await client.get(f"{GROUP}/dists/stable/main/binary-amd64/Packages", headers=root)
    hashed = await client.get(
        f"{GROUP}/dists/trixie/main/binary-amd64/by-hash/SHA256/{'a' * 64}", headers=root
    )

    assert theirs.content == mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"]
    assert names(ours.content) == [("megooarti-hello", OURS)]
    assert hashed.status_code == 404  # asked of the mirror, which has no such file
    assert "/debian/dists/trixie/main/binary-amd64/by-hash/SHA256/" + "a" * 64 in mirror.paths()


async def test_a_package_comes_from_the_first_member_that_has_it(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    ours = await client.get(f"{GROUP}/{OURS}", headers=root)
    theirs = await client.get(f"{GROUP}/pool/main/h/hello/hello_2.10-5_amd64.deb", headers=root)

    assert ours.content == make_deb()
    assert theirs.content == b"hello from the mirror"


async def test_a_suite_several_members_have_is_merged_and_an_earlier_members_package_wins(
    client, db, root, mirror
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())
    await upload(
        client,
        root,
        make_deb(control_text(package="libc6", version="2.41-6", architecture="amd64")),
    )

    key = (await client.get(f"{GROUP}/public.key", headers=root)).content
    release = verified(
        (await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)).content, key
    )
    packed = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)
    plain = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages", headers=root)

    # Whose suite it is, as its first proxy member says.
    assert release.startswith(
        b"Origin: Debian\nLabel: Debian\nSuite: trixie\nCodename: trixie\nVersion: 13.7\n"
    )
    assert names(gzip.decompress(packed.content)) == [
        ("libc6", "pool/main/libc/libc6/libc6_2.41-6_amd64.deb"),
        ("megooarti-hello", OURS),
        ("hello", "pool/main/h/hello/hello_2.10-5_amd64.deb"),
    ]
    listed = releases.parse(release + b"\n").entries
    text = gzip.decompress(packed.content)
    # The text is named, as apt needs, and not kept.
    assert (
        listed["main/binary-amd64/Packages"].size,
        listed["main/binary-amd64/Packages"].sha256,
    ) == (
        len(text),
        hashlib.sha256(text).hexdigest(),
    )
    assert (
        listed["main/binary-amd64/Packages.gz"].size,
        listed["main/binary-amd64/Packages.gz"].sha256,
    ) == (
        len(packed.content),
        hashlib.sha256(packed.content).hexdigest(),
    )
    assert plain.status_code == 404


async def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_and_says_why(
    db, admin_client, mirror
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db, keys=other_key())
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(admin_client, {}, make_deb())

    packed = await admin_client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz")
    shown = (await admin_client.get("/api/v1/repositories/apt-debian")).json()

    assert names(gzip.decompress(packed.content)) == [("megooarti-hello", OURS)]
    assert shown["status"]["last_error"].startswith(
        "Left out of the group apt-public: its InRelease is not signed by its remote's keys"
    )


def other_key() -> str:
    from megooarti.repositories import signing

    return signing.generate_openpgp("Not the mirror").public_key


async def test_a_suite_only_a_member_that_was_left_out_has_is_not_found(client, db, root, mirror):
    await a_proxy(db, keys=other_key())
    await a_group(db, "apt-debian")

    response = await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)

    assert response.status_code == 404


async def test_a_packages_file_that_is_not_the_one_its_release_names_is_left_out(
    client, db, root, mirror
):
    mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"] = lzma.compress(
        paragraph("evil", "1.0")
    )
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    packed = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)

    assert names(gzip.decompress(packed.content)) == [("megooarti-hello", OURS)]


async def test_a_suite_is_written_once_until_a_member_changes(
    client, db, root, mirror, monkeypatch
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    written = []
    merged = apt_groups._merged

    async def counted(*arguments):
        written.append(1)
        return await merged(*arguments)

    monkeypatch.setattr(apt_groups, "_merged", counted)

    await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)
    await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)
    assert len(written) == 1
    await upload(client, root, make_deb())
    await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)  # written again, behind
    await written_behind()
    assert len(written) == 2


async def test_a_suite_no_member_has_is_not_found(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_group(db, "apt-hosted")

    assert (await client.get(f"{GROUP}/dists/bookworm/InRelease", headers=root)).status_code == 404


async def test_the_group_signs_with_a_key_of_its_own(admin_client, db, mirror):
    await create(db, "apt-hosted")
    await a_group(db, "apt-hosted")

    groups = (await admin_client.get("/api/v1/repositories/apt-public/signing-key")).json()
    hosted = (await admin_client.get("/api/v1/repositories/apt-hosted/signing-key")).json()

    assert groups["fingerprint"] != hosted["fingerprint"]
    assert (await admin_client.get(f"{GROUP}/public.key")).text == groups["public_key"]


async def test_a_proxy_without_its_remotes_keys_cannot_be_a_member(admin_client):
    for body in (
        {"name": "apt-hosted", "format": "apt", "type": "hosted"},
        {
            "name": "apt-debian",
            "format": "apt",
            "type": "proxy",
            "proxy": {"remote_url": "http://deb.debian.org/debian"},
        },
    ):
        assert (await admin_client.post("/api/v1/repositories", json=body)).status_code == 201

    refused = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apt-public",
            "format": "apt",
            "type": "group",
            "group": {"members": ["apt-hosted", "apt-debian"]},
        },
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "group.members"


async def test_a_proxys_remote_keys_are_kept_and_shown(admin_client):
    keys = mirror_key().public_key

    made = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "apt-debian",
            "format": "apt",
            "type": "proxy",
            "proxy": {"remote_url": "http://deb.debian.org/debian"},
            "format_config": {"remote_keys": keys},
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["format_config"] == {"remote_keys": keys}


async def test_a_group_takes_no_upload(client, db, root, mirror):
    await create(db, "apt-hosted")
    await a_group(db, "apt-hosted")

    response = await upload(client, root, make_deb(), repository="apt-public")

    assert response.status_code == 405


# --- what the review of plan 12b found -------------------------------------------------


async def test_a_request_that_waits_for_a_suite_has_given_its_connection_back(
    client, db, root, mirror, monkeypatch
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    happened = []
    release, written = RepositoryContext.release, apt_groups.derived.written

    async def released(self):
        happened.append(f"release {self.repository.name}")
        return await release(self)

    async def waited(*arguments, **options):
        happened.append("wait")
        return await written(*arguments, **options)

    monkeypatch.setattr(RepositoryContext, "release", released)
    monkeypatch.setattr(apt_groups.derived, "written", waited)

    await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)

    assert happened.index("release apt-public") < happened.index("wait")


async def test_a_suite_is_written_with_a_session_of_its_own(client, db, root, mirror, monkeypatch):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    asked, used = [], []
    leaves, offer = apt_groups.group.leaves, apt_groups._offer

    async def recorded_leaves(context):
        asked.append(context.db)
        return await leaves(context)

    async def recorded_offer(member, suite, now):
        used.append(member.db)
        return await offer(member, suite, now)

    monkeypatch.setattr(apt_groups.group, "leaves", recorded_leaves)
    monkeypatch.setattr(apt_groups, "_offer", recorded_offer)

    response = await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)

    assert response.status_code == 200
    assert len(used) == 2 and all(session is not asked[0] for session in used)


async def test_a_member_whose_release_says_so_is_read_by_hash(client, db, root, fake_remote):
    fake_remote.files.update(mirror_files("trixie", {"main/binary-amd64": MIRRORED}, by_hash=True))
    # A mirror half way through a change: the file by its name is not the one named.
    fake_remote.files["debian/dists/trixie/main/binary-amd64/Packages.xz"] = lzma.compress(b"")
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    packed = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)

    assert [name for name, _ in names(gzip.decompress(packed.content))] == [
        "megooarti-hello",
        "hello",
        "libc6",
    ]


async def test_what_was_written_with_a_member_left_out_is_written_again_after_a_while(
    client, db, root, mirror, monkeypatch
):
    good = mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"]
    mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"] = lzma.compress(b"")
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())
    address = f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz"
    monkeypatch.setattr(apt_groups, "RETRY", timedelta(0))

    without = await client.get(address, headers=root)
    mirror.files["debian/dists/trixie/main/binary-amd64/Packages.xz"] = good
    await client.get(f"{GROUP}/dists/trixie/InRelease", headers=root)  # written again, behind
    await written_behind()
    again = await client.get(address, headers=root)

    assert [name for name, _ in names(gzip.decompress(without.content))] == ["megooarti-hello"]
    assert [name for name, _ in names(gzip.decompress(again.content))] == [
        "megooarti-hello",
        "hello",
        "libc6",
    ]


async def test_while_a_member_cannot_be_checked_the_last_index_is_served(client, db, root, mirror):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())
    before = (await client.get(f"{GROUP}/dists/trixie/Release", headers=root)).content
    # The mirror is now signed with a key it was not given: it is left out.
    mirror.files.update(
        mirror_files(
            "trixie",
            {"main/binary-amd64": MIRRORED},
            key=signing.generate_openpgp("Not the mirror"),
            moment=MIRRORED_AT + timedelta(days=1),
        )
    )

    await client.get(f"{GROUP}/dists/trixie/Release", headers=root)  # written again, behind
    await written_behind()
    after = (await client.get(f"{GROUP}/dists/trixie/Release", headers=root)).content

    assert after == before


async def test_a_suites_date_does_not_go_back_when_a_member_goes(db, mirror, admin_client):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(admin_client, {}, make_deb())
    address = f"{GROUP}/dists/trixie/Release"
    before = releases.parse((await admin_client.get(address)).content).moment

    changed = await admin_client.put(
        "/api/v1/repositories/apt-public", json={"group": {"members": ["apt-debian"]}}
    )
    await admin_client.get(address)  # written again, behind
    await written_behind()
    after = releases.parse((await admin_client.get(address)).content).moment

    assert changed.status_code == 200, changed.text
    assert before > MIRRORED_AT and after >= before


async def test_a_member_whose_release_has_expired_is_left_out(client, db, root, fake_remote):
    fake_remote.files.update(
        mirror_files(
            "trixie",
            {"main/binary-amd64": MIRRORED},
            valid_until=datetime(2000, 1, 1, tzinfo=UTC),
        )
    )
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    packed = await client.get(f"{GROUP}/dists/trixie/main/binary-amd64/Packages.gz", headers=root)

    assert [name for name, _ in names(gzip.decompress(packed.content))] == ["megooarti-hello"]


async def test_a_merged_release_is_valid_no_longer_than_its_members_are(
    client, db, root, fake_remote
):
    until = datetime(2099, 1, 1, tzinfo=UTC)
    fake_remote.files.update(
        mirror_files("trixie", {"main/binary-amd64": MIRRORED}, valid_until=until)
    )
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    await upload(client, root, make_deb())

    served = await client.get(f"{GROUP}/dists/trixie/Release", headers=root)
    release = releases.parse(served.content)

    assert release.valid_until == until


async def test_with_an_index_written_a_request_does_not_wait_for_the_next(
    client, db, root, mirror, monkeypatch
):
    await create(db, "apt-hosted", format_config={"suite": "trixie"})
    await a_proxy(db)
    await a_group(db, "apt-hosted", "apt-debian")
    address = f"{GROUP}/dists/trixie/Release"
    before = (await client.get(address, headers=root)).content
    await upload(client, root, make_deb())
    go = asyncio.Event()
    merged = apt_groups._merged

    async def slow(*arguments):
        await go.wait()
        return await merged(*arguments)

    monkeypatch.setattr(apt_groups, "_merged", slow)

    meanwhile = await asyncio.wait_for(client.get(address, headers=root), timeout=5)
    go.set()
    await written_behind()
    after = (await client.get(address, headers=root)).content

    assert meanwhile.content == before
    assert after != before
