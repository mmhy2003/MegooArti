import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import StreamingResponse

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from megooarti.storage.models import Blob
from tests.repositories.conftest import body, someone

EVERYTHING = someone("repository:raw:files")
HELLO = b"hello, world"


def request(method: str = "GET", **headers: str) -> Request:
    raw = [(name.replace("_", "-").encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw})


async def read(response) -> bytes:
    if isinstance(response, StreamingResponse):
        return b"".join([chunk async for chunk in response.body_iterator])
    return response.body


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def temporary_files(settings) -> list:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


async def test_put_stores_a_new_asset_with_its_component_and_blob(db, files, context_for):
    context = await context_for(files, EVERYTHING)

    asset, created = await context.put("docs/a.txt", body(HELLO))

    assert created is True
    assert (asset.path, asset.content_type, asset.kind) == ("docs/a.txt", "text/plain", "asset")
    assert asset.created_by == "dana"
    component = await db.get(Component, asset.component_id)
    assert (component.namespace, component.name, component.version) == ("docs", "a.txt", "")
    blob = await db.get(Blob, asset.blob_id)
    assert (blob.sha256, blob.size) == (hashlib.sha256(HELLO).hexdigest(), len(HELLO))
    assert await context.backend.exists(blob.sha256)
    assert temporary_files(context.settings) == []


async def test_put_replaces_an_existing_asset_and_releases_its_old_content(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    first, _ = await context.put("a.bin", body(b"first"))
    first_id, first_blob, first_updated = first.id, first.blob_id, first.updated_at

    second, created = await context.put("a.bin", body(b"second"))

    assert created is False
    assert second.id == first_id
    assert second.blob_id != first_blob
    assert second.updated_at > first_updated
    assert await count(db, Asset) == 1
    old = await db.get(Blob, first_blob, populate_existing=True)
    assert old.unreferenced_since is not None


async def test_the_same_content_at_two_paths_is_stored_once(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    one, _ = await context.put("one.bin", body(HELLO))
    two, _ = await context.put("two.bin", body(HELLO))

    assert one.blob_id == two.blob_id
    assert await count(db, Blob) == 1

    await context.delete("one.bin")

    shared = await db.get(Blob, two.blob_id, populate_existing=True)
    assert shared.unreferenced_since is None


@pytest.mark.parametrize(
    ("declared", "path", "expected"),
    [
        ("application/json", "a.bin", "application/json"),
        ("text/plain; charset=utf-8", "a.bin", "text/plain; charset=utf-8"),
        (None, "a.txt", "text/plain"),
        (None, "a.unknownextension", "application/octet-stream"),
        ("not a type", "a.txt", "text/plain"),
        ("text/html\r\nX-Evil: 1", "a.bin", "application/octet-stream"),
        ("x" * 300 + "/y", "a.bin", "application/octet-stream"),
    ],
)
async def test_content_type_is_the_declared_one_only_if_well_formed(
    files, context_for, declared, path, expected
):
    context = await context_for(files, EVERYTHING)

    asset, _ = await context.put(path, body(HELLO), content_type=declared)

    assert asset.content_type == expected


@pytest.mark.parametrize(
    "expectations",
    [
        {"expected_size": len(HELLO) + 1},
        {"expected_hashes": {"md5": "0" * 32}},
        {"expected_hashes": {"sha1": "0" * 40}},
        {"expected_hashes": {"sha256": "0" * 64}},
    ],
)
async def test_a_size_or_checksum_mismatch_stores_nothing(db, files, context_for, expectations):
    context = await context_for(files, EVERYTHING)

    error = await error_of(context.put("a.bin", body(HELLO), **expectations))

    assert (error.status_code, error.code) == (400, "checksum_mismatch")
    assert await count(db, Asset) == 0
    assert temporary_files(context.settings) == []


async def test_matching_size_and_checksums_are_accepted_in_any_case(files, context_for):
    context = await context_for(files, EVERYTHING)
    hashes = {
        "md5": hashlib.md5(HELLO).hexdigest().upper(),
        "sha1": hashlib.sha1(HELLO).hexdigest(),
        "sha256": f" {hashlib.sha256(HELLO).hexdigest()} ",
    }

    _, created = await context.put(
        "a.bin", body(HELLO), expected_size=len(HELLO), expected_hashes=hashes
    )

    assert created is True


async def test_an_interrupted_upload_stores_nothing(db, files, context_for):
    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise ConnectionError("the client went away")

    context = await context_for(files, EVERYTHING)

    with pytest.raises(ConnectionError):
        await context.put("a.bin", broken())

    assert await count(db, Asset) == 0
    assert temporary_files(context.settings) == []


async def test_no_database_connection_is_held_while_the_body_arrives(db, files, context_for):
    in_transaction = []

    async def watching() -> AsyncIterator[bytes]:
        in_transaction.append(db.in_transaction())
        yield HELLO

    context = await context_for(files, EVERYTHING)
    await context.put("a.bin", watching())

    assert in_transaction == [False]


@pytest.mark.parametrize(
    ("principal", "may_create", "may_replace"),
    [
        (someone("repository:raw:files:add"), True, False),
        (someone("repository:raw:files:edit"), False, True),
        (someone("repository:raw:files:read"), False, False),
        (someone("repository:raw:other"), False, False),
    ],
)
async def test_storing_needs_add_for_a_new_path_and_edit_for_an_existing_one(
    files, context_for, principal, may_create, may_replace
):
    seeded = await context_for(files, EVERYTHING)
    await seeded.put("existing.bin", body(b"old"))
    context = await context_for(files, principal)

    if may_create:
        assert (await context.put("new.bin", body(HELLO)))[1] is True
    else:
        assert (await error_of(context.put("new.bin", body(HELLO)))).code == "forbidden"
    if may_replace:
        assert (await context.put("existing.bin", body(HELLO)))[1] is False
    else:
        assert (await error_of(context.put("existing.bin", body(HELLO)))).code == "forbidden"


async def test_storing_without_a_principal_is_unauthorized_with_a_basic_challenge(
    files, context_for
):
    context = await context_for(files, None)

    error = await error_of(context.put("a.bin", body(HELLO)))

    assert error.status_code == 401
    assert error.headers == {"WWW-Authenticate": 'Basic realm="MegooArti"'}


async def test_a_read_only_repository_refuses_changes(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    await context.put("a.bin", body(HELLO))
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    stored = await error_of(context.put("b.bin", body(HELLO)))
    deleted = await error_of(context.delete("a.bin"))

    assert (stored.status_code, stored.code) == (403, "repository_read_only")
    assert (deleted.status_code, deleted.code) == (403, "repository_read_only")


async def test_disable_redeploy_allows_a_path_to_be_written_once(db, files, context_for):
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "disable_redeploy"}, format_config={}
    )
    context = await context_for(files, EVERYTHING)

    await context.put("a.bin", body(b"first"))
    error = await error_of(context.put("a.bin", body(b"second")))

    assert (error.status_code, error.code) == (409, "redeploy_disabled")
    assert await context.delete("a.bin") is True


@pytest.mark.parametrize("path", ["../escape", "a//b", ""])
async def test_an_invalid_path_is_rejected_everywhere(files, context_for, path):
    context = await context_for(files, EVERYTHING)

    for call in (
        context.put(path, body(HELLO)),
        context.delete(path),
        context.respond(path, request()),
    ):
        error = await error_of(call)
        assert (error.status_code, error.code) == (400, "invalid_path")


async def test_delete_removes_the_asset_its_component_and_releases_the_content(
    db, files, context_for
):
    context = await context_for(files, EVERYTHING)
    asset, _ = await context.put("docs/a.txt", body(HELLO))
    blob_id = asset.blob_id

    assert await context.delete("docs/a.txt") is True

    assert await count(db, Asset) == 0
    assert await count(db, Component) == 0
    blob = await db.get(Blob, blob_id, populate_existing=True)
    assert blob.unreferenced_since is not None
    assert await context.delete("docs/a.txt") is False


async def test_delete_needs_the_delete_permission(files, context_for):
    seeded = await context_for(files, EVERYTHING)
    await seeded.put("a.bin", body(HELLO))
    context = await context_for(files, someone("repository:raw:files:add"))

    assert (await error_of(context.delete("a.bin"))).code == "forbidden"


async def test_respond_sends_the_content_with_its_headers(files, context_for):
    context = await context_for(files, EVERYTHING)
    await context.put("docs/a.txt", body(HELLO))

    response = await context.respond("docs/a.txt", request())

    assert response.status_code == 200
    assert await read(response) == HELLO
    assert response.headers["Content-Length"] == str(len(HELLO))
    assert response.headers["ETag"] == f'"{hashlib.sha256(HELLO).hexdigest()}"'
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="a.txt"')


async def test_respond_honours_ranges_conditions_and_head(files, context_for):
    context = await context_for(files, EVERYTHING)
    await context.put("a.bin", body(HELLO))
    etag = f'"{hashlib.sha256(HELLO).hexdigest()}"'

    partial = await context.respond("a.bin", request(range="bytes=7-11"))
    unchanged = await context.respond("a.bin", request(if_none_match=etag))
    head = await context.respond("a.bin", request("HEAD"))

    assert (partial.status_code, await read(partial)) == (206, b"world")
    assert partial.headers["Content-Range"] == f"bytes 7-11/{len(HELLO)}"
    assert (unchanged.status_code, await read(unchanged)) == (304, b"")
    assert (head.status_code, await read(head)) == (200, b"")
    assert head.headers["Content-Length"] == str(len(HELLO))


async def test_respond_for_a_missing_path_is_not_found(files, context_for):
    context = await context_for(files, EVERYTHING)

    error = await error_of(context.respond("nothing/here.bin", request()))

    assert (error.status_code, error.code) == (404, "not_found")


async def test_a_download_is_noted_at_most_once_an_hour_and_never_for_head(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    asset, _ = await context.put("a.bin", body(HELLO))
    updated = asset.updated_at

    await context.respond("a.bin", request("HEAD"))
    assert asset.last_downloaded_at is None

    await context.respond("a.bin", request())
    first = asset.last_downloaded_at
    await context.respond("a.bin", request())
    assert first is not None
    assert asset.last_downloaded_at == first

    asset.last_downloaded_at = first - timedelta(hours=2)
    await db.flush()
    await context.respond("a.bin", request())

    assert asset.last_downloaded_at > first - timedelta(hours=2)
    assert asset.updated_at == updated


async def test_stage_then_store_joins_the_callers_transaction(db, files, context_for):
    context = await context_for(files, EVERYTHING)

    staged = await context.stage(body(HELLO))
    first, created = await context.store("pkg/one.bin", staged)
    second, _ = await context.store("pkg/two.bin", await context.stage(body(b"other")))

    assert created is True
    assert await count(db, Asset) == 2
    await db.rollback()  # a publish of several files that fails part-way leaves nothing
    assert await count(db, Asset) == 0
    assert await count(db, Component) == 0


async def test_stage_verifies_what_the_client_declared(files, context_for):
    context = await context_for(files, EVERYTHING)

    error = await error_of(context.stage(body(HELLO), expected_size=len(HELLO) + 1))

    assert (error.status_code, error.code) == (400, "checksum_mismatch")
    assert temporary_files(context.settings) == []


async def test_store_checks_permission_and_policy(files, context_for):
    context = await context_for(files, someone("repository:raw:files:read"))

    staged = await context.stage(body(HELLO))
    error = await error_of(context.store("a.bin", staged))

    assert error.code == "forbidden"
    assert temporary_files(context.settings) == []
