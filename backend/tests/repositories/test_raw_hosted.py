import hashlib
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.models import Asset
from megooarti.security import roles
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code

URL = "/repository/files/docs/a.txt"
HELLO = b"hello, world"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def test_put_then_get_returns_the_same_bytes_with_content_headers(client, files, root):
    stored = await client.put(URL, content=HELLO, headers=root)
    fetched = await client.get(URL, headers=root)

    assert (stored.status_code, stored.content) == (201, b"")
    assert (fetched.status_code, fetched.content) == (200, HELLO)
    digest = hashlib.sha256(HELLO).hexdigest()
    assert fetched.headers["ETag"] == f'"{digest}"'
    assert fetched.headers["X-Checksum-Sha256"] == digest
    assert fetched.headers["X-Checksum-Sha1"] == hashlib.sha1(HELLO).hexdigest()
    assert fetched.headers["Content-Type"] == "text/plain"
    assert fetched.headers["Content-Length"] == str(len(HELLO))
    assert fetched.headers["Content-Disposition"].startswith('attachment; filename="a.txt"')
    assert fetched.headers["X-Content-Type-Options"] == "nosniff"
    assert fetched.headers["Content-Security-Policy"] == "sandbox"


async def test_put_to_an_existing_path_replaces_it(client, files, root):
    await client.put(URL, content=b"first", headers=root)

    replaced = await client.put(URL, content=b"second", headers=root)

    assert replaced.status_code == 204
    assert (await client.get(URL, headers=root)).content == b"second"


async def test_head_sends_headers_only(client, files, root):
    await client.put(URL, content=HELLO, headers=root)

    response = await client.head(URL, headers=root)

    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["Content-Length"] == str(len(HELLO))


async def test_missing_things_are_not_found(client, files, root):
    missing_file = await client.get(URL, headers=root)
    missing_repository = await client.get("/repository/ghost/a.txt", headers=root)

    assert (missing_file.status_code, error_code(missing_file)) == (404, "not_found")
    assert (missing_repository.status_code, error_code(missing_repository)) == (404, "not_found")


async def test_delete(client, files, root):
    await client.put(URL, content=HELLO, headers=root)

    assert (await client.delete(URL, headers=root)).status_code == 204
    assert (await client.get(URL, headers=root)).status_code == 404
    assert (await client.delete(URL, headers=root)).status_code == 404


async def test_ranges_and_conditions(client, files, root):
    await client.put(URL, content=HELLO, headers=root)
    etag = (await client.head(URL, headers=root)).headers["ETag"]

    partial = await client.get(URL, headers={**root, "Range": "bytes=7-"})
    outside = await client.get(URL, headers={**root, "Range": "bytes=50-60"})
    unchanged = await client.get(URL, headers={**root, "If-None-Match": etag})

    assert (partial.status_code, partial.content) == (206, b"world")
    assert partial.headers["Content-Range"] == f"bytes 7-11/{len(HELLO)}"
    assert (outside.status_code, error_code(outside)) == (416, "range_not_satisfiable")
    assert outside.headers["Content-Range"] == f"bytes */{len(HELLO)}"
    assert (unchanged.status_code, unchanged.content) == (304, b"")


async def test_a_large_streamed_upload_round_trips(client, files, root):
    block = bytes(range(256)) * 4096  # 1 MiB
    blocks = 5

    async def stream() -> AsyncIterator[bytes]:
        for _ in range(blocks):
            yield block

    stored = await client.put("/repository/files/big.bin", content=stream(), headers=root)
    fetched = await client.get("/repository/files/big.bin", headers=root)

    assert stored.status_code == 201
    assert fetched.headers["Content-Length"] == str(blocks * len(block))
    assert hashlib.sha256(fetched.content).hexdigest() == hashlib.sha256(block * blocks).hexdigest()


async def test_a_declared_checksum_must_match(client, files, root):
    wrong = await client.put(URL, content=HELLO, headers={**root, "X-Checksum-Sha256": "0" * 64})
    right = await client.put(
        URL, content=HELLO, headers={**root, "X-Checksum-Sha1": hashlib.sha1(HELLO).hexdigest()}
    )

    assert (wrong.status_code, error_code(wrong)) == (400, "checksum_mismatch")
    assert right.status_code == 201


async def test_the_declared_content_type_is_kept(client, files, root):
    await client.put(URL, content=b"{}", headers={**root, "Content-Type": "application/json"})

    assert (await client.get(URL, headers=root)).headers["Content-Type"] == "application/json"


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_other_methods_are_not_allowed(client, files, root, method):
    response = await client.request(method, URL, content=HELLO, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, PUT, DELETE"


@pytest.mark.parametrize("path", ["a//b.txt", "trailing/", ""])
async def test_an_invalid_path_is_a_bad_request(client, files, root, path):
    response = await client.get(f"/repository/files/{path}", headers=root)
    assert (response.status_code, error_code(response)) == (400, "invalid_path")


async def test_no_credentials_gets_a_basic_challenge(client, files):
    for response in (await client.get(URL), await client.put(URL, content=HELLO)):
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
        assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_wrong_credentials_get_a_basic_challenge(client, files):
    response = await client.get(URL, headers=basic("nobody", "wrong password"))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_a_token_can_be_used_as_bearer_or_as_a_basic_password(
    client, files, make_user, make_token
):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    assert (await client.put(URL, content=HELLO, headers=bearer(token))).status_code == 201
    assert (await client.get(URL, headers=basic("root", token))).content == HELLO


async def test_each_action_needs_its_own_permission(client, files, root, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:raw:files:read"], [])
    await roles.create_role(db, "writers", "", ["repository:raw:files:add"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    await make_user("wes", roles=["writers"])
    reader, writer = basic("rae", PASSWORD), basic("wes", PASSWORD)

    by_reader = await client.put(URL, content=HELLO, headers=reader)
    by_writer = await client.put(URL, content=HELLO, headers=writer)
    replaced = await client.put(URL, content=b"again", headers=writer)
    read_by_writer = await client.get(URL, headers=writer)
    deleted = await client.delete(URL, headers=writer)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert by_writer.status_code == 201
    assert (replaced.status_code, error_code(replaced)) == (403, "forbidden")
    assert (read_by_writer.status_code, error_code(read_by_writer)) == (403, "forbidden")
    assert (deleted.status_code, error_code(deleted)) == (403, "forbidden")
    assert (await client.get(URL, headers=reader)).content == HELLO


async def test_a_permission_on_another_repository_does_not_apply(client, files, make_user, db):
    await roles.create_role(db, "elsewhere", "", ["repository:raw:other"], [])
    await db.commit()
    await make_user("eli", roles=["elsewhere"])

    response = await client.get(URL, headers=basic("eli", PASSWORD))

    assert (response.status_code, error_code(response)) == (403, "forbidden")


async def test_anonymous_access_allows_reading_but_not_writing(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    assert (await client.get(URL)).status_code == 401

    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    assert (await client.get(URL)).content == HELLO
    assert (await client.put(URL, content=b"defaced")).status_code == 401
    assert (await client.delete(URL)).status_code == 401


async def test_a_signed_in_user_without_roles_can_read_public_content(
    client, files, root, make_user, db
):
    await client.put(URL, content=HELLO, headers=root)
    await make_user("dana")
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    assert (await client.get(URL, headers=basic("dana", PASSWORD))).content == HELLO


async def test_a_browser_session_needs_the_csrf_token_to_upload(admin_client, files):
    refused = await admin_client.put(URL, content=HELLO, headers={"X-CSRF-Token": "wrong"})
    allowed = await admin_client.put(URL, content=HELLO)

    assert (refused.status_code, error_code(refused)) == (403, "csrf_failed")
    assert allowed.status_code == 201
    assert (await admin_client.get(URL)).content == HELLO


async def test_an_offline_repository_is_unavailable(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    await service.update_repository(db, files, online=False, hosted=None, format_config={})
    await db.commit()

    response = await client.get(URL, headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")


async def test_policies_apply_through_the_route(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "disable_redeploy"}, format_config={}
    )
    await db.commit()

    response = await client.put(URL, content=b"again", headers=root)

    assert (response.status_code, error_code(response)) == (409, "redeploy_disabled")
    assert (await client.get(URL, headers=root)).content == HELLO


async def test_a_download_is_recorded_on_the_asset(client, files, root, db):
    await client.put(URL, content=HELLO, headers=root)
    await client.head(URL, headers=root)
    assert await db.scalar(select(Asset.last_downloaded_at)) is None

    await client.get(URL, headers=root)

    assert await db.scalar(select(Asset.last_downloaded_at)) is not None


async def test_the_content_route_is_not_in_the_api_document(client):
    document = (await client.get("/api/v1/openapi.json")).json()
    assert not [path for path in document["paths"] if path.startswith("/repository")]
