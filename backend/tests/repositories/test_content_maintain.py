import pytest
from sqlalchemy import func, select

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import Asset
from tests.repositories.conftest import body, someone

ADD = someone("repository:raw:files:add")
EDIT = someone("repository:raw:files:edit")
READ = someone("repository:raw:files:read")
PATH = "acme/maven-metadata.xml"
XML = "application/xml"


def becomes(wanted: bytes | None):
    """An update that ignores what is stored."""

    async def update(current: bytes | None) -> bytes | None:
        return wanted

    return update


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def hosted(db, name: str, policy: str):
    return await service.create_repository(
        db,
        name=name,
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": policy},
        format_config={},
    )


@pytest.mark.parametrize("principal", [ADD, EDIT])
async def test_adding_or_editing_is_enough_to_write(files, context_for, principal):
    (await context_for(files, principal)).require_write()


async def test_reading_is_not_enough_to_write(files, context_for):
    readers = await context_for(files, READ)
    nobody = await context_for(files, None)

    with pytest.raises(ApiError) as forbidden:
        readers.require_write()
    with pytest.raises(ApiError) as unauthorised:
        nobody.require_write()

    assert (forbidden.value.status_code, forbidden.value.code) == (403, "forbidden")
    assert unauthorised.value.status_code == 401


async def test_nothing_is_written_to_a_read_only_repository(db, context_for):
    locked = await hosted(db, "locked", "read_only")
    context = await context_for(locked, someone("repository:raw:locked"))

    with pytest.raises(ApiError) as caught:
        context.require_write()

    assert (caught.value.status_code, caught.value.code) == (403, "repository_read_only")


async def test_maintain_stores_a_document_of_the_metadata_kind(files, context_for):
    context = await context_for(files, ADD)
    seen = []

    async def update(current: bytes | None) -> bytes | None:
        seen.append(current)
        return b"<plugins/>"

    await context.maintain(PATH, update, content_type=XML, limit=1000)

    stored = await context.stat(PATH)
    asset = await context.get(PATH)
    assert seen == [None]
    assert (stored.kind, stored.content_type, stored.size) == ("metadata", XML, 10)
    assert await context.read(PATH, limit=1000) == b"<plugins/>"
    assert (asset.component_id, asset.created_by) == (None, "dana")


async def test_maintain_hands_the_stored_bytes_to_the_update(files, context_for):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)
    seen = []

    async def update(current: bytes | None) -> bytes | None:
        seen.append(current)
        return current + b" two"

    await context.maintain(PATH, update, content_type=XML, limit=1000)

    assert seen == [b"one"]
    assert await context.read(PATH, limit=1000) == b"one two"


async def test_maintain_removes_the_document_when_the_update_returns_nothing(
    db, files, context_for
):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)

    await context.maintain(PATH, becomes(None), content_type=XML, limit=1000)
    await context.maintain(PATH, becomes(None), content_type=XML, limit=1000)

    assert await context.stat(PATH) is None
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_an_unchanged_document_is_left_alone(files, context_for):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"same"), content_type=XML, limit=1000)
    before = (await context.stat(PATH)).modified

    await context.maintain(PATH, becomes(b"same"), content_type=XML, limit=1000)

    assert (await context.stat(PATH)).modified == before


async def test_maintain_replaces_despite_disable_redeploy_and_without_edit(db, context_for):
    once = await hosted(db, "once", "disable_redeploy")
    context = await context_for(once, someone("repository:raw:once:add"))
    await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)

    await context.maintain(PATH, becomes(b"two"), content_type=XML, limit=1000)

    assert await context.read(PATH, limit=1000) == b"two"


async def test_maintain_never_touches_a_file_that_is_not_metadata(files, context_for):
    context = await context_for(files, someone("repository:raw:files"))
    await context.put("acme/app.jar", body(b"an artifact"))

    replaced = await error_of(
        context.maintain("acme/app.jar", becomes(b"overwritten"), content_type=XML, limit=1000)
    )
    removed = await error_of(
        context.maintain("acme/app.jar", becomes(None), content_type=XML, limit=1000)
    )

    assert (replaced.status_code, replaced.code) == (409, "conflict")
    assert (removed.status_code, removed.code) == (409, "conflict")
    assert await context.read("acme/app.jar", limit=1000) == b"an artifact"


async def test_maintain_needs_permission_to_write(files, context_for):
    context = await context_for(files, READ)

    error = await error_of(context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000))

    assert error.status_code == 403
    assert await context.stat(PATH) is None


async def test_only_a_hosted_repository_takes_uploads(mirror, context_for):
    context = await context_for(mirror, someone("repository:raw:mirror"))

    with pytest.raises(RuntimeError):
        context.require_write()
    with pytest.raises(RuntimeError):
        await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)


async def test_maintain_refuses_a_document_larger_than_it_could_read_back(files, context_for):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"x" * 1000), content_type=XML, limit=1000)

    error = await error_of(
        context.maintain(PATH, becomes(b"x" * 1001), content_type=XML, limit=1000)
    )

    assert (error.status_code, error.code) == (413, "payload_too_large")
    assert await context.read(PATH, limit=1000) == b"x" * 1000
