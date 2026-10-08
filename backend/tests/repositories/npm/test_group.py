import asyncio
import hashlib

import pytest
import structlog

from megooarti.repositories import service
from megooarti.repositories.npm import format as npm_format
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, bearer, error_code
from tests.repositories.npm.conftest import create, publish, remote_document, tarball_of

GROUP = "/repository/public"
HERE = "https://test/repository/public"


@pytest.fixture
async def public(db, registry, npmjs):
    """The hosted `npm` and the proxy `npmjs`, in that order."""
    return await create(db, "public", type="group", group={"members": ["npm", "npmjs"]})


async def document(client, headers, package: str, group: str = "public") -> dict:
    response = await client.get(f"/repository/{group}/{package}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def links(body: dict) -> list[str]:
    return [version["dist"]["tarball"] for version in body["versions"].values()]


async def take_offline(db, name: str) -> None:
    repository = await service.get_repository(db, name)
    repository.online = False
    await db.commit()


async def test_a_package_we_host_comes_from_us_and_the_remote_is_not_asked(
    client, root, public, fake_remote
):
    await publish(client, root, "left-pad", "1.0.0")

    body = await document(client, root, "left-pad")
    tarball = await client.get(f"{GROUP}/left-pad/-/left-pad-1.0.0.tgz", headers=root)

    assert list(body["versions"]) == ["1.0.0"]
    assert links(body) == [f"{HERE}/left-pad/-/left-pad-1.0.0.tgz"]  # the group, not `npm`
    assert tarball.content == tarball_of("left-pad", "1.0.0")
    assert fake_remote.requests == []


async def test_a_package_only_the_remote_has_comes_through_the_proxy(
    client, root, public, fake_remote
):
    fake_remote.files["registry/is-number"] = remote_document("is-number", "6.0.0", "7.0.0")
    fake_remote.files["registry/is-number/-/is-number-7.0.0.tgz"] = tarball_of("is-number", "7.0.0")

    first = await client.get(f"{GROUP}/is-number", headers=root)
    direct = await client.get("/repository/npmjs/is-number", headers=root)
    tarball = await client.get(f"{GROUP}/is-number/-/is-number-7.0.0.tgz", headers=root)

    assert links(first.json()) == [
        f"{HERE}/is-number/-/is-number-6.0.0.tgz",
        f"{HERE}/is-number/-/is-number-7.0.0.tgz",
    ]
    assert "Content-Length" not in first.headers  # sent as it is rewritten, never held
    # The same cached file, but not the same content: the links differ.
    assert first.headers["ETag"] != direct.headers["ETag"]
    assert tarball.content == tarball_of("is-number", "7.0.0")
    assert fake_remote.paths() == [
        "/registry/is-number",
        "/registry/is-number/-/is-number-7.0.0.tgz",
    ]


async def test_a_public_package_cannot_add_versions_to_a_name_we_host(
    client, root, public, fake_remote
):
    # Dependency confusion: the same name at the remote, with a higher version.
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "99.0.0")
    fake_remote.files["registry/internal-tool/-/internal-tool-99.0.0.tgz"] = b"hostile"

    body = await document(client, root, "internal-tool")
    theirs = await client.get(f"{GROUP}/internal-tool/-/internal-tool-99.0.0.tgz", headers=root)

    assert list(body["versions"]) == ["1.0.0"]
    assert body["dist-tags"] == {"latest": "1.0.0"}
    assert (theirs.status_code, error_code(theirs)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_a_public_package_cannot_stand_in_for_a_version_we_host(
    client, root, db, registry, npmjs, fake_remote
):
    # The proxy is tried first here, and the remote has the very version we host.
    await create(db, "remote-first", type="group", group={"members": ["npmjs", "npm"]})
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool/-/internal-tool-1.0.0.tgz"] = b"hostile"

    body = await document(client, root, "internal-tool", "remote-first")
    tarball = await client.get(
        "/repository/remote-first/internal-tool/-/internal-tool-1.0.0.tgz", headers=root
    )

    ours = tarball_of("internal-tool", "1.0.0")
    assert body["versions"]["1.0.0"]["dist"]["shasum"] == hashlib.sha1(ours).hexdigest()
    assert tarball.content == ours
    assert fake_remote.requests == []


async def test_a_name_an_offline_repository_holds_is_not_answered_by_the_remote(
    client, root, public, fake_remote, db
):
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "99.0.0")
    fake_remote.files["registry/internal-tool/-/internal-tool-99.0.0.tgz"] = b"hostile"
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    await take_offline(db, "npm")

    ours = await client.get(f"{GROUP}/internal-tool", headers=root)
    tarball = await client.get(f"{GROUP}/internal-tool/-/internal-tool-99.0.0.tgz", headers=root)
    theirs = await document(client, root, "is-number")

    assert (ours.status_code, error_code(ours)) == (503, "repository_offline")
    assert (tarball.status_code, error_code(tarball)) == (503, "repository_offline")
    assert list(theirs["versions"]) == ["7.0.0"]  # a name nobody here holds is still served
    assert fake_remote.paths() == ["/registry/is-number"]


async def test_a_name_held_behind_an_offline_group_is_not_answered_by_the_remote(
    client, root, db, registry, npmjs, fake_remote
):
    await create(db, "inner", type="group", group={"members": ["npm"]})
    await create(db, "outer", type="group", group={"members": ["inner", "npmjs"]})
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "99.0.0")
    await take_offline(db, "inner")

    response = await client.get("/repository/outer/internal-tool", headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")
    assert fake_remote.requests == []


async def test_an_offline_proxy_is_left_out(client, root, public, fake_remote, db):
    await publish(client, root, "left-pad", "1.0.0")
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    await take_offline(db, "npmjs")

    ours = await document(client, root, "left-pad")
    theirs = await client.get(f"{GROUP}/is-number", headers=root)

    assert list(ours["versions"]) == ["1.0.0"]
    assert (theirs.status_code, error_code(theirs)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_hosted_members_are_merged_and_the_earlier_one_wins(client, root, db):
    await create(db, "npm")
    await create(db, "team")
    await create(db, "both", type="group", group={"members": ["npm", "team"]})
    await publish(client, root, "left-pad", "1.0.0", description="from npm")
    await publish(client, root, "left-pad", "1.0.0", repository="team", description="from team")
    await publish(client, root, "left-pad", "2.0.0-beta.1", repository="team", tag="beta")

    body = await document(client, root, "left-pad", "both")
    tarball = await client.get("/repository/both/left-pad/-/left-pad-1.0.0.tgz", headers=root)
    later = await client.get("/repository/both/left-pad/-/left-pad-2.0.0-beta.1.tgz", headers=root)

    assert list(body["versions"]) == ["1.0.0", "2.0.0-beta.1"]
    assert body["versions"]["1.0.0"]["description"] == "from npm"
    assert body["dist-tags"] == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}
    assert all(link.startswith("https://test/repository/both/left-pad/-/") for link in links(body))
    assert tarball.content == tarball_of("left-pad", "1.0.0")
    assert later.content == tarball_of("left-pad", "2.0.0-beta.1")


async def test_the_merged_document_is_answered_like_any_content(client, root, public):
    await publish(client, root, "left-pad", "1.0.0")
    first = await client.get(f"{GROUP}/left-pad", headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(f"{GROUP}/left-pad", headers={**root, "If-None-Match": etag})
    headed = await client.head(f"{GROUP}/left-pad", headers=root)

    assert first.headers["Content-Type"] == "application/json"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, headed.status_code, headed.content) == (304, 200, b"")


@pytest.fixture
async def mirrors(db, fake_remote):
    """Proxies `first` and `second` of two remotes that both have left-pad, in one group."""
    await create(db, "first", type="proxy", proxy={"remote_url": "http://remote.test/a"})
    await create(db, "second", type="proxy", proxy={"remote_url": "http://remote.test/b"})
    fake_remote.files["a/left-pad"] = remote_document(
        "left-pad", "1.0.0", "1.1.0", remote="http://remote.test/a", description="from a"
    )
    fake_remote.files["b/left-pad"] = remote_document(
        "left-pad", "1.1.0", "2.0.0", remote="http://remote.test/b", description="from b, " * 40
    )
    return await create(db, "mirrors", type="group", group={"members": ["first", "second"]})


async def test_two_proxies_that_both_have_a_package_are_merged(client, root, mirrors, fake_remote):
    fake_remote.files["a/left-pad/-/left-pad-1.1.0.tgz"] = b"from a"
    fake_remote.files["b/left-pad/-/left-pad-1.1.0.tgz"] = b"from b"
    fake_remote.files["b/left-pad/-/left-pad-2.0.0.tgz"] = b"only b"

    first = await client.get("/repository/mirrors/left-pad", headers=root)
    again = await client.get(
        "/repository/mirrors/left-pad", headers={**root, "If-None-Match": first.headers["ETag"]}
    )
    shared = await client.get("/repository/mirrors/left-pad/-/left-pad-1.1.0.tgz", headers=root)
    theirs = await client.get("/repository/mirrors/left-pad/-/left-pad-2.0.0.tgz", headers=root)

    body = first.json()
    assert list(body["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]
    assert body["dist-tags"] == {"latest": "1.1.0"}  # the earlier member's
    assert body["description"] == "from a"
    assert links(body) == [
        f"https://test/repository/mirrors/left-pad/-/left-pad-{version}.tgz"
        for version in ("1.0.0", "1.1.0", "2.0.0")
    ]
    assert first.headers["ETag"] == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert again.status_code == 304
    assert (shared.content, theirs.content) == (b"from a", b"only b")


async def test_documents_too_large_to_merge_together_are_not_merged_and_it_is_logged(
    client, root, mirrors, fake_remote, monkeypatch
):
    # The second proxy's document is the longer one. Either fits; both do not.
    monkeypatch.setattr(npm_format, "MERGE_LIMIT", len(fake_remote.files["b/left-pad"]))

    with structlog.testing.capture_logs() as logs:
        body = await document(client, root, "left-pad", "mirrors")

    assert list(body["versions"]) == ["1.0.0", "1.1.0"]
    assert links(body)[0] == "https://test/repository/mirrors/left-pad/-/left-pad-1.0.0.tgz"
    too_large = [entry for entry in logs if entry["event"] == "document_too_large_to_merge"]
    assert [(entry["repository"], entry["package"]) for entry in too_large] == [
        ("second", "left-pad")
    ]


async def test_at_most_two_merges_are_in_memory_at_once_and_publishes_do_not_hold_them_up():
    running, most = 0, 0

    async def one() -> None:
        nonlocal running, most
        async with npm_format.merging():
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.01)
            running -= 1

    async with npm_format.publishing(), npm_format.publishing():
        await asyncio.wait_for(asyncio.gather(*(one() for _ in range(6))), timeout=5)

    assert most == 2


async def test_a_later_proxy_does_not_stand_in_for_an_earlier_one_that_is_too_large(
    client, root, mirrors, fake_remote, monkeypatch
):
    # Here the first proxy's document is the one that does not fit.
    longer = remote_document(
        "left-pad", "1.0.0", "1.1.0", remote="http://remote.test/a", description="from a, " * 80
    )
    fake_remote.files["a/left-pad"] = longer
    monkeypatch.setattr(npm_format, "MERGE_LIMIT", len(longer) - 1)

    with structlog.testing.capture_logs() as logs:
        body = await document(client, root, "left-pad", "mirrors")

    # The first member's document alone, as its tarballs are the first to be served.
    assert list(body["versions"]) == ["1.0.0", "1.1.0"]
    assert body["description"].startswith("from a")
    too_large = [entry for entry in logs if entry["event"] == "document_too_large_to_merge"]
    assert [entry["repository"] for entry in too_large] == ["first"]


async def test_a_document_that_cannot_be_read_is_left_out_and_logged(
    client, root, mirrors, fake_remote
):
    fake_remote.files["a/left-pad"] = b"<html>not a package document</html>"

    with structlog.testing.capture_logs() as logs:
        body = await document(client, root, "left-pad", "mirrors")

    assert list(body["versions"]) == ["1.1.0", "2.0.0"]
    assert links(body)[0] == "https://test/repository/mirrors/left-pad/-/left-pad-1.1.0.tgz"
    unreadable = [entry for entry in logs if entry["event"] == "document_unreadable"]
    assert [entry["repository"] for entry in unreadable] == ["first"]


async def test_only_one_of_two_proxies_having_a_package_is_not_a_merge(
    client, root, mirrors, fake_remote
):
    fake_remote.files["b/is-number"] = remote_document(
        "is-number", "7.0.0", remote="http://remote.test/b"
    )

    response = await client.get("/repository/mirrors/is-number", headers=root)

    assert links(response.json()) == [
        "https://test/repository/mirrors/is-number/-/is-number-7.0.0.tgz"
    ]
    assert "Content-Length" not in response.headers  # streamed, not built


async def test_nobody_has_it(client, root, public, fake_remote):
    missing = await client.get(f"{GROUP}/no-such-package", headers=root)
    fake_remote.down = True
    unreachable = await client.get(f"{GROUP}/another-package", headers=root)
    tarball = await client.get(f"{GROUP}/another-package/-/another-package-1.0.0.tgz", headers=root)

    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert (unreachable.status_code, error_code(unreachable)) == (404, "not_found")
    assert (tarball.status_code, error_code(tarball)) == (404, "not_found")


async def test_a_group_inside_a_group(client, root, public, fake_remote, db):
    await create(db, "extra")
    await create(db, "outer", type="group", group={"members": ["public", "extra"]})
    await publish(client, root, "left-pad", "1.0.0")
    await publish(client, root, "left-pad", "3.0.0", repository="extra")
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    fake_remote.files["registry/is-number/-/is-number-7.0.0.tgz"] = tarball_of("is-number", "7.0.0")

    ours = await document(client, root, "left-pad", "outer")
    theirs = await document(client, root, "is-number", "outer")
    tarball = await client.get("/repository/outer/is-number/-/is-number-7.0.0.tgz", headers=root)

    assert list(ours["versions"]) == ["1.0.0", "3.0.0"]
    assert links(theirs) == ["https://test/repository/outer/is-number/-/is-number-7.0.0.tgz"]
    assert tarball.content == tarball_of("is-number", "7.0.0")


async def test_reading_through_the_group_needs_read_on_the_group_only(
    client, root, public, fake_remote, make_user, db
):
    await publish(client, root, "left-pad", "1.0.0")
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    members = ["repository:npm:npm:read", "repository:npm:npmjs:read"]
    await roles.create_role(db, "group-readers", "", ["repository:npm:public:read"], [])
    await roles.create_role(db, "member-readers", "", members, [])
    await db.commit()
    await make_user("gina", roles=["group-readers"])
    await make_user("mel", roles=["member-readers"])
    gina, mel = basic("gina", PASSWORD), basic("mel", PASSWORD)

    ours = await document(client, gina, "left-pad")
    theirs = await document(client, gina, "is-number")
    tarball = await client.get(f"{GROUP}/left-pad/-/left-pad-1.0.0.tgz", headers=gina)
    refused = await client.get(f"{GROUP}/left-pad", headers=mel)

    assert (list(ours["versions"]), list(theirs["versions"])) == (["1.0.0"], ["7.0.0"])
    assert tarball.status_code == 200
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_signing_in_works_on_a_group_and_changing_packages_does_not(
    client, public, make_user
):
    await make_user("dana", roles=["admin"])
    login = f"{GROUP}/-/user/org.couchdb.user:dana"

    signed_in = await client.put(login, json={"name": "dana", "password": PASSWORD})
    token = bearer(signed_in.json()["token"])
    who = await client.get(f"{GROUP}/-/whoami", headers=token)
    published = await publish(client, token, "left-pad", "1.0.0", repository="public")
    tagged = await client.put(
        f"{GROUP}/-/package/left-pad/dist-tags/x", json="1.0.0", headers=token
    )
    removed = await client.delete(f"{GROUP}/left-pad/-/left-pad-1.0.0.tgz", headers=token)
    one_version = await client.get(f"{GROUP}/left-pad/latest", headers=token)
    tags = await client.get(f"{GROUP}/-/package/left-pad/dist-tags", headers=token)

    assert (signed_in.status_code, who.json()) == (201, {"username": "dana"})
    for response in (published, tagged, removed, one_version, tags):
        assert (response.status_code, error_code(response)) == (405, "method_not_allowed")


async def test_search_covers_every_member_and_lists_a_package_once(
    client, root, public, fake_remote
):
    await publish(client, root, "left-pad", "1.0.0", description="ours")
    await publish(client, root, "our-pad", "1.0.0")
    fake_remote.files["registry/left-pad/-/left-pad-9.0.0.tgz"] = b"theirs"
    fake_remote.files["registry/pad-right/-/pad-right-2.0.0.tgz"] = b"theirs"
    for path in ("left-pad/-/left-pad-9.0.0.tgz", "pad-right/-/pad-right-2.0.0.tgz"):
        await client.get(f"/repository/npmjs/{path}", headers=root)  # into the proxy's cache

    response = await client.get(f"{GROUP}/-/v1/search", params={"text": "pad"}, headers=root)
    page = await client.get(
        f"{GROUP}/-/v1/search", params={"text": "pad", "size": 1, "from": 1}, headers=root
    )

    found = [
        (entry["package"]["name"], entry["package"]["version"], entry["package"]["description"])
        for entry in response.json()["objects"]
    ]
    # What we host is described by us, whatever a proxy has cached under the same name.
    assert found == [
        ("left-pad", "1.0.0", "ours"),
        ("our-pad", "1.0.0", ""),
        ("pad-right", "2.0.0", ""),
    ]
    assert response.json()["total"] == 3
    assert [entry["package"]["name"] for entry in page.json()["objects"]] == ["our-pad"]
    assert page.json()["total"] == 3
