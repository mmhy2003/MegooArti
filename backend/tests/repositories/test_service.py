import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import (
    Asset,
    NegativeCacheEntry,
    ProxyState,
    Repository,
    RepositoryMember,
)
from megooarti.secrets_box import Sealed
from megooarti.storage.models import Blob, BlobStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def create(db, name="files", **fields):
    fields.setdefault("format", "raw")
    fields.setdefault("type", "hosted")
    fields.setdefault("online", True)
    fields.setdefault("blob_store", "default")
    fields.setdefault("hosted", None)
    fields.setdefault("format_config", {})
    return await service.create_repository(db, name=name, **fields)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def test_create_a_hosted_repository(db):
    repository = await create(db)

    view = await service.describe(db, repository)

    assert view == service.RepositoryView(
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        url_path="/repository/files/",
        hosted={"deployment_policy": "allow_redeploy"},
        format_config={},
    )


async def test_names_are_unique_ignoring_case_but_looked_up_exactly(db):
    await create(db, "Files")

    assert (await error_of(create(db, "files"))).code == "conflict"
    assert await service.get_repository(db, "Files") is not None
    assert await service.get_repository(db, "files") is None


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"format": "cobol"}, "format"),
        ({"type": "proxy"}, "proxy.remote_url"),
        ({"type": "group", "group": {"members": ["ghost"]}}, "group.members"),
        ({"blob_store": "ghost"}, "blob_store"),
        ({"hosted": {"deployment_policy": "sometimes"}}, "hosted.deployment_policy"),
        ({"format_config": {"anything": 1}}, "format_config"),
    ],
)
async def test_invalid_repositories_are_rejected(db, override, field):
    error = await error_of(create(db, **override))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == field


async def test_update_changes_online_and_policy_only(db):
    repository = await create(db)

    await service.update_repository(
        db, repository, online=False, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    view = await service.describe(db, repository)
    assert (view.online, view.hosted) == (False, {"deployment_policy": "read_only"})
    assert (view.name, view.format, view.type, view.blob_store) == (
        "files",
        "raw",
        "hosted",
        "default",
    )


async def test_update_validates_like_create(db):
    repository = await create(db)

    error = await error_of(
        service.update_repository(
            db, repository, online=True, hosted={"deployment_policy": "no"}, format_config={}
        )
    )

    assert error.code == "validation_error"


async def test_delete_removes_content_and_marks_its_blobs_unreferenced(db):
    repository = await create(db)
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id,
        sha256="a" * 64,
        md5="b" * 32,
        sha1="c" * 40,
        sha512="d" * 128,
        size=1,
    )
    db.add(blob)
    await db.flush()
    db.add(
        Asset(
            repository_id=repository.id,
            path="a.bin",
            blob_id=blob.id,
            content_type="application/octet-stream",
            created_by="dana",
        )
    )
    await db.flush()

    await service.delete_repository(db, repository, NOW)
    await db.refresh(blob)

    assert await service.get_repository(db, "files") is None
    assert await db.scalar(select(Asset.id)) is None
    assert blob.unreferenced_since == NOW


async def test_list_is_paged_in_name_order(db):
    for name in ("zeta", "alpha", "Beta"):
        await create(db, name)

    page, total = await service.list_repositories(db, limit=2, offset=1)

    assert total == 3
    assert [view.name for view in page] == ["Beta", "zeta"]
    assert await db.scalar(select(Repository.name_key).where(Repository.name == "Beta")) == "beta"


async def test_a_repository_with_very_many_assets_can_be_deleted(db):
    repository = await create(db)
    store = await db.scalar(select(BlobStore))
    many = 33_000  # more than one statement may carry as arguments
    blob_ids = [uuid.uuid4() for _ in range(many)]
    await db.execute(
        insert(Blob),
        [
            {
                "id": blob_id,
                "blob_store_id": store.id,
                "sha256": f"{number:064x}",
                "md5": "b" * 32,
                "sha1": "c" * 40,
                "sha512": "d" * 128,
                "size": 1,
                "created_at": NOW,
            }
            for number, blob_id in enumerate(blob_ids)
        ],
    )
    await db.execute(
        insert(Asset),
        [
            {
                "id": uuid.uuid4(),
                "repository_id": repository.id,
                "path": f"file-{number}.bin",
                "blob_id": blob_id,
                "content_type": "application/octet-stream",
                "kind": "asset",
                "attributes": {},
                "created_by": "dana",
                "created_at": NOW,
                "updated_at": NOW,
            }
            for number, blob_id in enumerate(blob_ids)
        ],
    )

    await service.delete_repository(db, repository, NOW)

    assert await db.scalar(select(func.count()).select_from(Asset)) == 0
    unmarked = select(func.count()).select_from(Blob).where(Blob.unreferenced_since.is_(None))
    assert await db.scalar(unmarked) == 0


REMOTE = {"remote_url": "https://remote.example/files/"}
SECRET = Sealed("enc:v1:sealed-by-the-caller")


async def proxy(db, name="mirror", **settings):
    return await create(db, name, type="proxy", proxy={**REMOTE, **settings})


async def group(db, name="all", members=()):
    return await create(db, name, type="group", group={"members": list(members)})


async def test_create_a_proxy_repository_with_defaults(db):
    view = await service.describe(db, await proxy(db))

    assert (view.type, view.blob_store, view.hosted, view.group) == (
        "proxy",
        "default",
        None,
        None,
    )
    assert view.proxy == {
        "remote_url": "https://remote.example/files",
        "content_max_age_minutes": 1440,
        "metadata_max_age_minutes": 1440,
        "negative_cache": {"enabled": True, "ttl_minutes": 1440},
        "remote_auth": {"type": "none", "username": "", "has_secret": False},
        "blocked": False,
        "auto_block": True,
    }
    assert view.status == {
        "blocked": False,
        "auto_blocked_until": None,
        "failures": 0,
        "last_error": None,
    }


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        ({"remote_url": ""}, "proxy.remote_url"),
        ({"remote_url": "ftp://remote.example"}, "proxy.remote_url"),
        ({"remote_url": "https://"}, "proxy.remote_url"),
        ({"remote_url": "https://remote.example/?token=1"}, "proxy.remote_url"),
        ({"content_max_age_minutes": -2}, "proxy.content_max_age_minutes"),
        ({"metadata_max_age_minutes": "soon"}, "proxy.metadata_max_age_minutes"),
        ({"negative_cache": {"ttl_minutes": 0}}, "proxy.negative_cache.ttl_minutes"),
        ({"remote_auth": {"type": "kerberos"}}, "proxy.remote_auth.type"),
        ({"remote_auth": {"type": "basic", "secret": SECRET}}, "proxy.remote_auth.username"),
        ({"remote_auth": {"type": "basic", "username": "u"}}, "proxy.remote_auth.secret"),
        ({"remote_auth": {"type": "bearer"}}, "proxy.remote_auth.secret"),
    ],
)
async def test_invalid_proxy_settings_are_rejected(db, settings, field):
    error = await error_of(proxy(db, **settings))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == field


async def test_a_remote_secret_is_stored_sealed_and_never_shown(db):
    auth = {"type": "basic", "username": "robot", "secret": SECRET}
    repository = await proxy(db, remote_auth=auth)

    view = await service.describe(db, repository)

    assert repository.config["proxy"]["remote_auth"]["secret"] == SECRET
    assert view.proxy["remote_auth"] == {"type": "basic", "username": "robot", "has_secret": True}


async def test_a_remote_secret_that_is_not_sealed_is_a_programming_error(db):
    auth = {"type": "bearer", "secret": "a plain string"}

    with pytest.raises(TypeError):
        await proxy(db, remote_auth=auth)


async def test_updating_without_a_secret_keeps_the_stored_one(db):
    repository = await proxy(
        db, remote_auth={"type": "basic", "username": "robot", "secret": SECRET}
    )

    await service.update_repository(
        db,
        repository,
        online=True,
        proxy={**REMOTE, "remote_auth": {"type": "basic", "username": "robot-2"}},
    )

    stored = repository.config["proxy"]["remote_auth"]
    assert (stored["username"], stored["secret"]) == ("robot-2", SECRET)


async def test_changing_the_kind_of_credential_needs_a_new_secret(db):
    repository = await proxy(
        db, remote_auth={"type": "basic", "username": "robot", "secret": SECRET}
    )

    error = await error_of(
        service.update_repository(
            db, repository, online=True, proxy={**REMOTE, "remote_auth": {"type": "bearer"}}
        )
    )

    assert error.details[0]["field"] == "proxy.remote_auth.secret"


async def test_removing_the_credential_forgets_the_secret(db):
    repository = await proxy(db, remote_auth={"type": "bearer", "secret": SECRET})

    await service.update_repository(db, repository, online=True, proxy=REMOTE)

    assert repository.config["proxy"]["remote_auth"] == {"type": "none"}


async def test_create_a_group_with_ordered_members(db):
    await create(db, "releases")
    await proxy(db, "mirror")

    repository = await group(db, members=["mirror", "releases"])
    view = await service.describe(db, repository)

    assert (view.type, view.blob_store, view.hosted, view.proxy) == ("group", None, None, None)
    assert view.group == {"members": ["mirror", "releases"]}
    assert [member.name for member in await service.members(db, repository)] == [
        "mirror",
        "releases",
    ]


async def test_updating_a_group_replaces_its_members_and_order(db):
    for name in ("one", "two", "three"):
        await create(db, name)
    repository = await group(db, members=["one", "two"])

    await service.update_repository(
        db, repository, online=True, group={"members": ["three", "one"]}
    )

    assert await service.member_names(db, repository) == ["three", "one"]


async def test_a_group_may_be_empty(db):
    assert (await service.describe(db, await group(db))).group == {"members": []}


async def test_a_member_must_exist_once_and_share_the_format(db):
    await create(db, "releases")
    other = Repository(name="jars", name_key="jars", format="another-format", type="hosted")
    db.add(other)
    await db.flush()

    unknown = await error_of(group(db, "a", members=["ghost"]))
    twice = await error_of(group(db, "b", members=["releases", "releases"]))
    foreign = await error_of(group(db, "c", members=["jars"]))

    for error in (unknown, twice, foreign):
        assert (error.status_code, error.code) == (422, "validation_error")
        assert error.details[0]["field"] == "group.members"


async def test_a_group_cannot_contain_itself_directly_or_indirectly(db):
    inner = await group(db, "inner")
    await group(db, "outer", members=["inner"])

    direct = await error_of(
        service.update_repository(db, inner, online=True, group={"members": ["inner"]})
    )
    indirect = await error_of(
        service.update_repository(db, inner, online=True, group={"members": ["outer"]})
    )

    assert (direct.status_code, direct.code) == (409, "repository_cycle")
    assert (indirect.status_code, indirect.code) == (409, "repository_cycle")
    assert await service.member_names(db, inner) == []


async def test_a_repository_a_group_presents_cannot_be_deleted(db):
    member = await create(db, "releases")
    presenting = await group(db, members=["releases"])

    error = await error_of(service.delete_repository(db, member, NOW))
    assert (error.status_code, error.code) == (409, "in_use")

    await service.update_repository(db, presenting, online=True, group={"members": []})
    await service.delete_repository(db, member, NOW)

    assert await service.get_repository(db, "releases") is None


async def test_deleting_a_group_leaves_its_members(db):
    await create(db, "releases")
    presenting = await group(db, members=["releases"])

    await service.delete_repository(db, presenting, NOW)

    assert await service.get_repository(db, "releases") is not None
    assert await db.scalar(select(func.count()).select_from(RepositoryMember)) == 0


async def test_invalidating_a_proxy_cache_is_refused_for_other_types(db):
    hosted = await create(db, "releases")

    error = await error_of(service.invalidate_cache(db, hosted))

    assert (error.status_code, error.code) == (409, "not_a_proxy")


@pytest.mark.parametrize(
    "url",
    [
        "https://robot:hunter2@remote.example/files",
        "https://robot@remote.example/files",
        "http://remote.example:abc/files",
        "http://[::1/files",
        "http://:80/files",
    ],
)
async def test_a_remote_url_must_be_well_formed_and_carry_no_credentials(db, url):
    error = await error_of(proxy(db, remote_url=url))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == "proxy.remote_url"
    assert "hunter2" not in str(error.details)


async def test_the_stored_secret_does_not_follow_a_change_of_remote_host(db):
    repository = await proxy(db, remote_auth={"type": "bearer", "secret": SECRET})
    elsewhere = {"remote_url": "https://attacker.example/files", "remote_auth": {"type": "bearer"}}

    error = await error_of(service.update_repository(db, repository, online=True, proxy=elsewhere))

    assert error.details[0]["field"] == "proxy.remote_auth.secret"


@pytest.mark.parametrize(
    "url", ["http://remote.example/files", "https://remote.example:8443/files"]
)
async def test_a_change_of_scheme_or_port_also_needs_the_secret_again(db, url):
    repository = await proxy(db, remote_auth={"type": "bearer", "secret": SECRET})

    error = await error_of(
        service.update_repository(
            db,
            repository,
            online=True,
            proxy={"remote_url": url, "remote_auth": {"type": "bearer"}},
        )
    )

    assert error.details[0]["field"] == "proxy.remote_auth.secret"


async def test_the_stored_secret_is_kept_when_only_the_path_changes(db):
    repository = await proxy(db, remote_auth={"type": "bearer", "secret": SECRET})
    moved = {"remote_url": "https://remote.example/other", "remote_auth": {"type": "bearer"}}

    await service.update_repository(db, repository, online=True, proxy=moved)

    assert repository.config["proxy"]["remote_auth"]["secret"] == SECRET


async def learn_about_the_remote(db, repository) -> Asset:
    """Give a proxy a block, a remembered miss and a cached, verified file."""
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id,
        sha256="f" * 64,
        md5="b" * 32,
        sha1="c" * 40,
        sha512="d" * 128,
        size=1,
    )
    db.add(blob)
    await db.flush()
    asset = Asset(
        repository_id=repository.id,
        path="cached.bin",
        blob_id=blob.id,
        content_type="application/octet-stream",
        created_by="proxy",
        last_verified_at=NOW,
    )
    db.add_all(
        [
            asset,
            ProxyState(repository_id=repository.id, failures=3, blocked_until=NOW, last_error="x"),
            NegativeCacheEntry(repository_id=repository.id, path="missing.bin", expires_at=NOW),
        ]
    )
    await db.flush()
    return asset


async def test_updating_a_proxy_lifts_an_automatic_block(db):
    repository = await proxy(db)
    asset = await learn_about_the_remote(db, repository)

    await service.update_repository(db, repository, online=True, proxy=REMOTE)
    await db.refresh(asset)

    assert await db.scalar(select(func.count()).select_from(ProxyState)) == 0
    assert asset.last_verified_at == NOW  # the same remote: its cache is still good
    assert await db.scalar(select(func.count()).select_from(NegativeCacheEntry)) == 1


async def test_pointing_a_proxy_somewhere_else_forgets_what_the_old_remote_said(db):
    repository = await proxy(db)
    asset = await learn_about_the_remote(db, repository)

    await service.update_repository(
        db, repository, online=True, proxy={"remote_url": "https://remote.example/other"}
    )
    await db.refresh(asset)

    assert asset.last_verified_at is None
    assert await db.scalar(select(func.count()).select_from(NegativeCacheEntry)) == 0
    assert await db.scalar(select(func.count()).select_from(ProxyState)) == 0


async def test_updating_a_group_needs_its_members_stated(db):
    await create(db, "releases")
    repository = await group(db, members=["releases"])

    error = await error_of(service.update_repository(db, repository, online=False))

    assert (error.status_code, error.details[0]["field"]) == (422, "group")
    assert await service.member_names(db, repository) == ["releases"]
