import pytest
from sqlalchemy import select
from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import ComponentInfo
from megooarti.repositories.formats import ComponentKey, Format
from megooarti.repositories.models import Asset, Component
from megooarti.system.settings_store import set_setting
from tests.repositories.conftest import someone

EVERYTHING = someone("repository:raw:files")


class Packaged(Format):
    """Files at namespace/name/version/file belong to a package; others to none."""

    name = "raw"

    def describe_component(self, path):
        parts = path.split("/")
        return ComponentKey(*parts[:3]) if len(parts) == 4 else None


def request(url: str = "http://internal.example:8000/repository/files/x") -> Request:
    scheme, _, rest = url.partition("://")
    host, _, path = rest.partition("/")
    name, _, port = host.partition(":")
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        "server": (name, int(port or 80)),
        "path": f"/{path}",
        "root_path": "",
        "headers": [(b"host", host.encode())],
    }
    return Request(scope)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


@pytest.fixture
async def context(files, context_for):
    made = await context_for(files, EVERYTHING)
    made.format = Packaged()
    return made


async def store(context, path: str, content: bytes = b"x", **options):
    staged = await context.stage_bytes(content)
    return await context.store(path, staged, **options)


async def test_storing_can_describe_the_component(context, db):
    asset, created = await store(context, "acme/app/1.0/app.tgz", component_attributes={"a": 1})

    component = await db.get(Component, asset.component_id)
    assert created is True
    assert component.attributes == {"a": 1}


async def test_storing_again_replaces_the_description(context, db):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"a": 1})

    asset, created = await store(
        context, "acme/app/1.0/app.tgz", b"new", component_attributes={"a": 2}
    )
    untouched, _ = await store(context, "acme/app/1.0/app.tgz", b"newer")

    component = await db.get(Component, asset.component_id, populate_existing=True)
    assert created is False
    assert component.attributes == {"a": 2}
    assert untouched.component_id == asset.component_id


async def test_a_second_file_of_a_component_can_describe_it_too(context, db):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"a": 1})
    await store(context, "acme/app/1.0/app.sig", component_attributes={"a": 3})

    assert list(await db.scalars(select(Component.attributes))) == [{"a": 3}]


async def test_bytes_in_memory_are_staged_and_can_be_discarded(context, settings, db):
    staged = await context.stage_bytes(b"y" * 3_000_000)
    temporary = settings.data_dir / "blobs" / "default" / "tmp"

    assert staged.size == 3_000_000
    assert len(list(temporary.iterdir())) == 1
    await context.discard(staged)
    assert list(temporary.iterdir()) == []
    assert await db.scalar(select(Asset)) is None


async def test_components_lists_a_packages_versions_with_their_attributes(context):
    first, _ = await store(context, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    extra, _ = await store(context, "acme/app/1.0/app.sig")
    second, _ = await store(context, "acme/app/2.0/app.tgz", component_attributes={"n": 2})
    await store(context, "acme/other/1.0/other.tgz")
    await store(context, "elsewhere/app/1.0/app.tgz")

    held = sorted(await context.components("acme", "app"), key=lambda info: info.version)

    assert [info.version for info in held] == ["1.0", "2.0"]
    assert [info.attributes for info in held] == [{"n": 1}, {"n": 2}]
    assert held[0].modified == max(first.updated_at, extra.updated_at)
    assert held[1].modified == second.updated_at
    assert isinstance(held[0], ComponentInfo) and held[0].created <= held[0].modified
    assert await context.components("acme", "nothing") == []


async def test_annotate_changes_a_components_attributes(context, db):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"n": 1})

    changed = await context.annotate("acme", "app", "1.0", {"n": 1, "deprecated": "old"})
    missing = await context.annotate("acme", "app", "9.9", {"n": 9})

    assert (changed, missing) == (True, False)
    assert (await context.components("acme", "app"))[0].attributes == {"n": 1, "deprecated": "old"}


async def test_annotate_needs_edit_and_a_repository_that_takes_changes(db, files, context_for):
    writer = await context_for(files, EVERYTHING)
    writer.format = Packaged()
    await store(writer, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    adder = await context_for(files, someone("repository:raw:files:add"))
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    forbidden = await error_of(adder.annotate("acme", "app", "1.0", {"n": 2}))
    read_only = await error_of(writer.annotate("acme", "app", "1.0", {"n": 2}))

    assert (forbidden.status_code, forbidden.code) == (403, "forbidden")
    assert (read_only.status_code, read_only.code) == (403, "repository_read_only")
    assert (await writer.components("acme", "app"))[0].attributes == {"n": 1}


async def test_package_names_finds_packages_by_name_or_namespace(context):
    for path in (
        "acme/left-pad/1.0/a.tgz",
        "acme/left-pad/2.0/a.tgz",
        "acme/right-pad/1.0/a.tgz",
        "padding/tool/1.0/a.tgz",
        "zeta/unrelated/1.0/a.tgz",
        "loose.txt",
    ):
        await store(context, path)

    names, total = await context.package_names("PAD", limit=10, offset=0)
    page, page_total = await context.package_names("pad", limit=1, offset=1)
    everything, count = await context.package_names("", limit=10, offset=0)
    literal, _ = await context.package_names("left_pad", limit=10, offset=0)

    assert names == [("acme", "left-pad"), ("acme", "right-pad"), ("padding", "tool")]
    assert total == 3
    assert (page, page_total) == ([("acme", "right-pad")], 3)
    assert (len(everything), count) == (4, 4)
    assert literal == []


async def test_the_public_address_is_the_requests_unless_one_is_configured(context, db):
    from_request = await context.public_url(request())
    await set_setting(db, "base_url", "https://packages.example/")

    configured = await context.public_url(request())

    assert from_request == "http://internal.example:8000/repository/files"
    assert configured == "https://packages.example/repository/files"
