"""What the repositories' and blob stores' administration writes to the audit log (spec 9):
each repository made, changed and deleted, with what changed and never its remote's
secret; its cache, index and signing key; and each blob store."""

from tests.audit import last

REPOSITORIES = "/api/v1/repositories"
MIRROR = {
    "name": "mirror",
    "format": "raw",
    "type": "proxy",
    "proxy": {
        "remote_url": "https://remote.example/files",
        "remote_auth": {"type": "basic", "username": "robot", "secret": "hunter2-the-remote"},
    },
}


async def test_a_repository_made_changed_and_deleted_is_recorded_without_its_secret(
    admin_client, sessionmaker
):
    await admin_client.post(REPOSITORIES, json=MIRROR)
    await admin_client.put(f"{REPOSITORIES}/mirror", json={**MIRROR, "online": False})
    await admin_client.post(f"{REPOSITORIES}/mirror/invalidate-cache")
    await admin_client.delete(f"{REPOSITORIES}/mirror")

    created = await last(sessionmaker, "repository.created")
    updated = await last(sessionmaker, "repository.updated")
    deleted = await last(sessionmaker, "repository.deleted")
    assert (created.actor, created.target_kind, created.target_name) == (
        "root",
        "repository",
        "mirror",
    )
    assert created.changes["format"] == {"before": None, "after": "raw"}
    assert created.changes["proxy.remote_auth.secret"] == {
        "before": "[redacted]",
        "after": "[redacted]",
    }
    assert "status" not in created.changes
    assert updated.changes["online"] == {"before": True, "after": False}
    assert "hunter2-the-remote" not in str([created.changes, updated.changes])
    assert (await last(sessionmaker, "repository.cache_invalidated")).target_name == "mirror"
    assert deleted.changes["name"] == {"before": "mirror", "after": None}


async def test_a_signing_key_made_is_recorded_by_its_fingerprint(admin_client, sessionmaker):
    await admin_client.post(
        REPOSITORIES, json={"name": "apt-hosted", "format": "apt", "type": "hosted"}
    )

    shown = await admin_client.post(f"{REPOSITORIES}/apt-hosted/signing-key/generate", json={})

    generated = await last(sessionmaker, "signing_key.generated")
    assert generated.target_name == "apt-hosted"
    assert generated.changes["fingerprint"] == {
        "before": None,
        "after": shown.json()["fingerprint"],
    }


async def test_an_index_rebuilt_is_recorded_with_what_was_done(admin_client, sessionmaker):
    await admin_client.post(REPOSITORIES, json={"name": "files", "format": "raw", "type": "hosted"})

    await admin_client.post(f"{REPOSITORIES}/files/rebuild-index")

    rebuilt = await last(sessionmaker, "repository.index_rebuilt")
    assert rebuilt.target_name == "files"
    assert set(rebuilt.changes) == {"files", "moved", "components", "removed"}


async def test_a_blob_store_made_and_deleted_is_recorded(admin_client, sessionmaker):
    await admin_client.post("/api/v1/blob-stores", json={"name": "archive"})
    await admin_client.delete("/api/v1/blob-stores/archive")

    created = await last(sessionmaker, "blob_store.created")
    assert created.changes == {
        "path": {"before": None, "after": "archive"},
        "type": {"before": None, "after": "file"},
    }
    assert (await last(sessionmaker, "blob_store.deleted")).target_name == "archive"
