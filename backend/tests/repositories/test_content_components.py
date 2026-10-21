import hashlib

import pytest
from sqlalchemy import select
from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import ComponentInfo, PackageFile
from megooarti.repositories.formats import ComponentKey, Format
from megooarti.repositories.models import Asset, Component
from megooarti.system.settings_store import set_setting
from tests.repositories.conftest import someone

EVERYTHING = someone("repository:raw:files")


class Packaged(Format):
    """Files at namespace/name/version/file belong to a package; others to none."""

    name = "raw"

    def describe_component(self, path, attributes=None):
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


APP = "acme/app/1.0/app.tgz"


async def test_annotate_changes_a_components_attributes(context, db):
    await store(context, APP, component_attributes={"n": 1})

    changed = await context.annotate("acme", "app", "1.0", {"n": 1, "deprecated": "old"}, path=APP)
    missing = await context.annotate("acme", "app", "9.9", {"n": 9}, path=APP)

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

    forbidden = await error_of(adder.annotate("acme", "app", "1.0", {"n": 2}, path=APP))
    read_only = await error_of(writer.annotate("acme", "app", "1.0", {"n": 2}, path=APP))

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


async def test_component_reads_one_version(context):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    await store(context, "acme/app/2.0/app.tgz", component_attributes={"n": 2})

    found = await context.component("acme", "app", "2.0")

    assert (found.version, found.attributes) == ("2.0", {"n": 2})
    assert await context.component("acme", "app", "9.9") is None


async def test_package_names_can_cover_several_repositories(context, context_for, db):
    more = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    second = await context_for(more, someone("repository:raw:more"))
    second.format = Packaged()
    await store(context, "acme/left-pad/1.0/a.tgz")
    await store(context, "acme/only-here/1.0/a.tgz")
    await store(second, "acme/left-pad/3.0/a.tgz")
    await store(second, "zeta/pad-there/1.0/a.tgz")
    both = [context, second]

    names, total = await context.package_names("", limit=10, offset=0, within=both)
    page, page_total = await context.package_names("pad", limit=1, offset=1, within=both)
    alone = await second.package_names("", limit=10, offset=0)
    nowhere = await context.package_names("", limit=10, offset=0, within=[])

    # A package both hold is listed once.
    assert names == [("acme", "left-pad"), ("acme", "only-here"), ("zeta", "pad-there")]
    assert total == 3
    assert (page, page_total) == ([("zeta", "pad-there")], 2)
    assert alone == ([("acme", "left-pad"), ("zeta", "pad-there")], 2)
    assert nowhere == ([], 0)


async def test_package_files_lists_every_file_of_every_version(context):
    first, _ = await store(
        context,
        "acme/app/1.0/app.tgz",
        b"one",
        attributes={"kind": "source"},
        component_attributes={"n": 1},
    )
    second, _ = await store(context, "acme/app/1.0/app.whl", b"three")
    third, _ = await store(
        context, "acme/app/2.0/app.tgz", b"second", component_attributes={"n": 2}
    )
    await store(context, "acme/other/1.0/other.tgz")
    await store(context, "other/app/1.0/app.tgz")
    await store(context, "loose.txt")

    files = await context.package_files("acme", "app")

    assert files == [
        PackageFile(
            path="acme/app/1.0/app.tgz",
            version="1.0",
            size=3,
            sha256=hashlib.sha256(b"one").hexdigest(),
            modified=first.updated_at,
            attributes={"kind": "source"},
            component_attributes={"n": 1},
        ),
        PackageFile(
            path="acme/app/1.0/app.whl",
            version="1.0",
            size=5,
            sha256=hashlib.sha256(b"three").hexdigest(),
            modified=second.updated_at,
            attributes={},
            component_attributes={"n": 1},
        ),
        PackageFile(
            path="acme/app/2.0/app.tgz",
            version="2.0",
            size=6,
            sha256=hashlib.sha256(b"second").hexdigest(),
            modified=third.updated_at,
            attributes={},
            component_attributes={"n": 2},
        ),
    ]
    assert await context.package_files("acme", "nothing") == []


async def test_what_is_recorded_about_a_file_stays_until_it_is_given_again(context):
    await store(context, "acme/app/1.0/app.tgz", b"one", attributes={"kind": "source"})

    await store(context, "acme/app/1.0/app.tgz", b"two")
    kept = (await context.package_files("acme", "app"))[0].attributes
    await store(context, "acme/app/1.0/app.tgz", b"three", attributes={"kind": "rebuilt"})
    replaced = (await context.package_files("acme", "app"))[0].attributes

    assert (kept, replaced) == ({"kind": "source"}, {"kind": "rebuilt"})


class Recorded(Format):
    """A file belongs to the package its recorded attributes name, whatever its path."""

    name = "raw"

    def describe_component(self, path, attributes=None):
        said = (attributes or {}).get("package")
        return None if said is None else ComponentKey("", said["name"], said["version"])


async def test_a_format_is_told_what_was_recorded_of_a_file_to_say_its_component(
    files, context_for, db
):
    context = await context_for(files, EVERYTHING)
    context.format = Recorded()

    asset, _ = await store(
        context, "pool/x.deb", attributes={"package": {"name": "hello", "version": "1:2.0"}}
    )

    component = await db.get(Component, asset.component_id)
    assert (component.name, component.version) == ("hello", "1:2.0")


async def test_rebuilding_an_index_tells_the_format_what_was_recorded_of_each_file(
    files, context_for, db
):
    context = await context_for(files, EVERYTHING)
    await store(context, "pool/x.deb", attributes={"package": {"name": "hello", "version": "1"}})
    await db.commit()
    context.format = Recorded()

    seen, moved, _ = await context.reindex()

    assert (seen, moved) == (1, 1)
    asset = await db.scalar(select(Asset).execution_options(populate_existing=True))
    component = await db.get(Component, asset.component_id)
    assert (component.name, component.version) == ("hello", "1")
