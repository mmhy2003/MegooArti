"""The preview (spec 4.4, CLN-3): what a policy, kept or not, would remove from a
repository now, a page at a time with the total, of what the caller may browse; nothing
is removed."""

import pytest

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic, error_code
from tests.cleanup.conftest import age, put

PREVIEW = "/api/v1/cleanup-policies/preview"
OLD = {"format": "raw", "updated_days": 30, "repository": "files"}


async def three_files(client, root, db) -> None:
    for path, days in (("a.txt", 40), ("b.txt", 50), ("c.txt", 1)):
        await put(client, root, path)
        await age(db, path, written=days)


async def test_the_preview_lists_what_a_policy_would_remove(client, root, db, files):
    await three_files(client, root, db)

    previewed = await client.post(PREVIEW, json=OLD, headers=root)

    assert previewed.status_code == 200, previewed.text
    body = previewed.json()
    assert body["total"] == 2
    assert [item["name"] for item in body["items"]] == ["a.txt", "b.txt"]  # newest first
    assert set(body["items"][0]) == {
        "id",
        "namespace",
        "name",
        "version",
        "modified",
        "last_downloaded",
    }
    assert body["items"][0]["last_downloaded"] is None
    assert (await client.get("/repository/files/b.txt", headers=root)).status_code == 200


async def test_the_preview_is_paged(client, root, db, files):
    await three_files(client, root, db)

    second = await client.post(f"{PREVIEW}?limit=1&offset=1", json=OLD, headers=root)

    assert second.json()["total"] == 2
    assert [item["name"] for item in second.json()["items"]] == ["b.txt"]


@pytest.mark.parametrize(
    ("changes", "status", "field"),
    [
        ({"release_type": "release"}, 422, "release_type"),
        ({"repository": "all"}, 422, "repository"),
        ({"format": "npm", "release_type": None}, 422, "repository"),
        ({"repository": "nowhere"}, 404, None),
    ],
)
async def test_what_cannot_be_previewed_is_refused(client, root, db, files, changes, status, field):
    await put(client, root, "a.txt")
    await client.post(
        "/api/v1/repositories",
        json={"name": "all", "format": "raw", "type": "group", "group": {"members": ["files"]}},
        headers=root,
    )

    refused = await client.post(PREVIEW, json={**OLD, **changes}, headers=root)

    assert refused.status_code == status, refused.text
    if field is not None:
        assert [detail["field"] for detail in refused.json()["error"]["details"]] == [field]
    else:
        assert error_code(refused) == "not_found"


async def test_the_preview_shows_only_what_the_caller_may_browse(
    client, root, db, sessionmaker, make_user, files
):
    for path in ("mine/a.txt", "theirs/b.txt"):
        await put(client, root, path)
        await age(db, path, written=40)
    db.add(ContentSelector(name="mine", description="", expression='path =^ "/mine/"'))
    await db.commit()
    async with sessionmaker() as session:
        held = ["admin:cleanup:read", "selector:mine:raw:files:browse"]
        await roles.create_role(session, "mine-cleaners", "", held, [])
        await session.commit()
    await make_user("mia", roles=["mine-cleaners"])

    previewed = await client.post(PREVIEW, json=OLD, headers=basic("mia", PASSWORD))

    assert previewed.json()["total"] == 1
    assert [item["name"] for item in previewed.json()["items"]] == ["a.txt"]


async def test_the_preview_needs_cleanup_read(client, make_user, files):
    await make_user("sam")

    refused = await client.post(PREVIEW, json=OLD, headers=basic("sam", PASSWORD))

    assert refused.status_code == 403
