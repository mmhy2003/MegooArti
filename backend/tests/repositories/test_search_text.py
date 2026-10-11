"""What a component is found by: the words each format gives it."""

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.formats import ComponentKey, Format
from megooarti.repositories.models import Component
from tests.accounts import PASSWORD, basic
from tests.repositories.conftest import someone
from tests.repositories.docker.conftest import push_image
from tests.repositories.npm.conftest import publish
from tests.repositories.pypi.conftest import upload


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str):
    made = await service.create_repository(
        db, name=name, format=format, type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    return made


async def texts(db, namespace: str | None = "") -> list[str]:
    found = select(Component.search).order_by(Component.search)
    if namespace is not None:
        found = found.where(Component.namespace == namespace)
    return list(await db.scalars(found))


def test_a_component_is_found_by_its_namespace_name_and_version_unless_its_format_adds_more():
    described = Format().search_text(ComponentKey("docs/api", "Index.html", ""), {})
    versioned = Format().search_text(ComponentKey("", "tool", "1.0"), {"anything": "ignored"})

    assert (described, versioned) == ("docs/api Index.html", "tool 1.0")


async def test_a_raw_file_is_found_by_its_folder_and_name_in_lower_case(client, files, root, db):
    await client.put("/repository/files/Docs/Guide.MD", content=b"x", headers=root)

    assert await texts(db, None) == ["docs guide.md"]


async def test_a_maven_artifact_is_found_by_its_coordinates(client, root, db):
    await create(db, "releases", "maven")
    await client.put(
        "/repository/releases/com/acme/app/1.0/app-1.0.jar", content=b"x", headers=root
    )

    assert await texts(db, None) == ["com.acme app 1.0 com.acme:app:1.0"]


async def test_an_npm_package_is_found_by_its_name_description_and_keywords(client, root, db):
    await create(db, "npm", "npm")
    await publish(
        client,
        root,
        "@acme/tool",
        "1.0.0",
        description="Cuts Things",
        keywords=["saw", "Blade", 7, {"not": "a word"}],
    )
    await publish(client, root, "plain", "2.0.0", description=["not text"], keywords="one two")

    assert await texts(db, None) == [
        "acme tool 1.0.0 @acme/tool saw blade cuts things",
        "plain 2.0.0 plain one two",
    ]


async def test_a_python_release_is_found_by_its_name_and_summary(client, root, db):
    await create(db, "pypi", "pypi")
    await upload(client, root, "greeter-1.0-py3-none-any.whl", summary="Says Hello")

    assert await texts(db, None) == ["greeter 1.0 says hello"]


async def test_a_docker_tag_is_found_as_people_write_images(client, root, db):
    await create(db, "images", "docker")
    await push_image(client, root, "team/app", "1.0", "one")

    assert await texts(db, "") == ["team/app 1.0 team/app:1.0"]


async def test_what_a_component_is_found_by_has_a_limit(client, root, db):
    await create(db, "npm", "npm")

    await publish(client, root, "tool", "1.0.0", description="word " * 5000)

    (text,) = await texts(db, None)
    assert len(text) == 4000 and text.startswith("tool 1.0.0 tool word word")


async def test_changing_what_is_said_about_a_component_changes_what_it_is_found_by(
    client, root, db, context_for
):
    repository = await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0", description="first words")
    context = await context_for(repository, someone("repository:npm:npm"))

    await context.annotate("", "tool", "1.0.0", {"npm": {"description": "Deprecated: use saw"}})
    await db.commit()

    assert await texts(db, None) == ["tool 1.0.0 tool deprecated: use saw"]


async def test_a_python_release_is_found_by_the_keywords_its_upload_declared(client, root, db):
    await create(db, "pypi", "pypi")
    await upload(
        client,
        root,
        "greeter-1.0-py3-none-any.whl",
        summary="Says Hello",
        keywords="Greeting, salutation\twave\x01",
    )

    assert await texts(db, None) == ["greeter 1.0 says hello greeting, salutation wave"]


async def test_npm_keywords_are_not_lost_behind_a_long_description(client, root, db):
    await create(db, "npm", "npm")

    await publish(client, root, "tool", "1.0.0", description="word " * 5000, keywords=["sawblade"])

    (text,) = await texts(db, None)
    assert len(text) == 4000 and text.startswith("tool 1.0.0 tool sawblade word word")
