"""Rebuilding a repository's index: every file to its component, every component its words."""

import pytest
from sqlalchemy import delete, func, select, update

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import someone
from tests.repositories.docker.conftest import push_image
from tests.repositories.npm.conftest import publish

REPOSITORIES = "/api/v1/repositories"
SEARCH = "/api/v1/search"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str, **settings):
    made = await service.create_repository(
        db,
        name=name,
        format=format,
        type=settings.pop("type", "hosted"),
        online=True,
        blob_store="default",
        **settings,
    )
    await db.commit()
    return made


async def deploy(client, root, *paths: str) -> None:
    for path in paths:
        response = await client.put(
            f"/repository/maven/{path}", content=path.encode(), headers=root
        )
        assert response.status_code == 201, response.text


async def found(client, root, **params) -> list[str]:
    response = await client.get(SEARCH, params=params, headers=root)
    return [f"{item['name']}:{item['version']}" for item in response.json()["items"]]


async def forget_components(db) -> None:
    """Leave the files as an older version would have: belonging to nothing."""
    await db.execute(update(Asset).values(component_id=None))
    await db.execute(delete(Component))
    await db.commit()


async def test_files_are_given_back_to_the_components_they_belong_to(client, root, db):
    await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar", "com/acme/app/1.0/app-1.0.pom")
    await deploy(client, root, "com/acme/lib/2.0/lib-2.0.jar")
    await forget_components(db)
    before = await found(client, root)

    response = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)

    assert before == []
    assert response.json() == {"files": 3, "moved": 3, "components": 2, "removed": 0}
    assert await found(client, root, q="com.acme:app:1.0") == ["app:1.0"]
    listed = await client.get(
        "/api/v1/content/maven/components", params={"name": "app"}, headers=root
    )
    opened = await client.get(
        f"/api/v1/content/maven/components/{listed.json()['items'][0]['id']}", headers=root
    )
    assert [file["name"] for file in opened.json()["files"]] == ["app-1.0.jar", "app-1.0.pom"]


async def test_what_components_are_found_by_is_written_again(client, root, db):
    await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0", description="Cuts wood")
    await db.execute(update(Component).values(search="tool 1.0.0"))  # as a migration left it
    await db.commit()
    before = await found(client, root, q="wood")

    response = await client.post(f"{REPOSITORIES}/npm/rebuild-index", headers=root)

    assert before == []
    assert response.json() == {"files": 2, "moved": 0, "components": 1, "removed": 0}
    assert await found(client, root, q="wood") == ["tool:1.0.0"]


async def test_a_second_rebuild_changes_nothing(client, root, db):
    await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar")

    first = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)
    second = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)

    assert first.json() == second.json() == {"files": 1, "moved": 0, "components": 1, "removed": 0}


async def test_a_file_with_the_wrong_component_is_moved_and_an_empty_component_goes(
    client, root, db
):
    repository = await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar", "com/acme/lib/2.0/lib-2.0.jar")
    stray = Component(repository_id=repository.id, namespace="x", name="stray", version="0")
    db.add(stray)
    await db.flush()
    await db.execute(update(Asset).where(Asset.path.like("%lib%")).values(component_id=stray.id))
    await db.commit()

    response = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)

    assert response.json() == {"files": 2, "moved": 1, "components": 3, "removed": 1}
    names = set(await db.scalars(select(Component.name)))
    assert names == {"app", "lib"}
    assert await found(client, root, name="lib") == ["lib:2.0"]


async def test_docker_manifests_kept_before_they_were_components_get_theirs(client, root, db):
    await create(db, "docker", "docker")
    await push_image(client, root, "team/app", "1.0", "one", repository="docker")
    await forget_components(db)

    response = await client.post(f"{REPOSITORIES}/docker/rebuild-index", headers=root)

    # A tag, a manifest, a configuration and a layer; the tag and the manifest are components.
    assert response.json() == {"files": 4, "moved": 2, "components": 2, "removed": 0}
    held = set(await db.execute(select(Component.namespace, Component.name, Component.version)))
    assert ("", "team/app", "1.0") in held
    assert {namespace for namespace, _, _ in held} == {"", "manifests"}
    assert await found(client, root) == ["team/app:1.0"]  # the manifest's is still not listed


async def test_what_a_format_keeps_for_itself_stays_with_no_component(client, root, db):
    await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0")

    await client.post(f"{REPOSITORIES}/npm/rebuild-index", headers=root)

    without = list(await db.scalars(select(Asset.path).where(Asset.component_id.is_(None))))
    assert without == ["-/package/tool/dist-tags"]


async def test_a_large_repository_is_gone_through_in_pieces(db, context_for, files):
    context = await context_for(files, someone("repository:raw:files"))
    for number in range(7):
        await context.store(f"logs/day-{number}", await context.stage_bytes(b"x"))
    await forget_components(db)
    looked_at, moved, after, pieces = 0, 0, "", 0

    while after is not None:
        seen, changed, after = await context.reindex(after=after, limit=3)
        looked_at, moved, pieces = looked_at + seen, moved + changed, pieces + 1
    described, removed, following = await context.redescribe(limit=3)
    rest = await context.redescribe(after=following, limit=100)

    assert (looked_at, moved, pieces) == (7, 7, 3)
    assert (described, removed, following is not None) == (3, 0, True)
    assert rest[:2] == (4, 0) and rest[2] is None
    assert await db.scalar(select(func.count()).select_from(Component)) == 7


async def test_a_group_has_no_index(client, root, db, files):
    await create(db, "all", "raw", type="group", group={"members": ["files"]})

    response = await client.post(f"{REPOSITORIES}/all/rebuild-index", headers=root)

    assert response.json() == {"files": 0, "moved": 0, "components": 0, "removed": 0}


async def test_rebuilding_is_an_administrators(client, root, db, files, make_user):
    everything = ["repository:raw:files", "admin:repositories:read"]
    await roles.create_role(db, "users", "", everything, [])
    await db.commit()
    await make_user("user", roles=["users"])

    refused = await client.post(
        f"{REPOSITORIES}/files/rebuild-index", headers=basic("user", PASSWORD)
    )
    nobody = await client.post(f"{REPOSITORIES}/files/rebuild-index")
    absent = await client.post(f"{REPOSITORIES}/nothing/rebuild-index", headers=root)

    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert nobody.status_code == 401
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_what_is_said_about_a_component_while_it_is_rebuilt_is_what_it_is_found_by(
    client, root, db, context_for, monkeypatch
):
    repository = await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0", description="first words")
    context = await context_for(repository, None)
    locking = context._lock_component

    async def changed_meanwhile(key) -> None:
        # Another request changes the description after the piece was read and before
        # this component's turn. It commits; here it is the same transaction.
        await db.execute(
            update(Component)
            .values(attributes={"npm": {"description": "second words"}})
            # As another session's change arrives: the rows this one loaded know nothing of it.
            .execution_options(synchronize_session=False)
        )
        await locking(key)

    monkeypatch.setattr(context, "_lock_component", changed_meanwhile)

    await context.redescribe()
    await db.commit()

    assert list(await db.scalars(select(Component.search))) == ["tool 1.0.0 tool second words"]


async def test_a_file_deleted_while_its_piece_is_gone_through_does_not_stop_the_rebuild(
    client, root, db, context_for, monkeypatch
):
    repository = await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar", "com/acme/lib/2.0/lib-2.0.jar")
    await forget_components(db)
    context = await context_for(repository, None)
    making = context._component

    async def deleted_meanwhile(key):
        # Another request deletes the first file after the piece was read.
        await db.execute(delete(Asset).where(Asset.path.like("%app%")))
        return await making(key)

    monkeypatch.setattr(context, "_component", deleted_meanwhile)

    seen, moved, after = await context.reindex()
    await context.redescribe()
    await db.commit()

    assert (seen, moved, after) == (2, 1, None)
    assert list(await db.scalars(select(Component.name))) == ["lib"]
