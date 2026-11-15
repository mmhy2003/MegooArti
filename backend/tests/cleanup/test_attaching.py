"""Cleanup policies attached to repositories (spec 4.3): hosted and proxy repositories,
policies of their format or of every format, kept by a `PUT` that does not name them, and
detached, each recorded, when a policy is deleted (E10)."""

import pytest

from tests.accounts import error_code
from tests.audit import last, records

POLICIES = "/api/v1/cleanup-policies"
REPOSITORIES = "/api/v1/repositories"


async def make_policy(client, name: str, format: str = "raw") -> None:
    made = await client.post(POLICIES, json={"name": name, "format": format, "updated_days": 30})
    assert made.status_code == 201, made.text


async def make_repository(client, name: str = "files2", **settings) -> dict:
    body = {"name": name, "format": "raw", "type": "hosted", **settings}
    made = await client.post(REPOSITORIES, json=body)
    assert made.status_code == 201, made.text
    return made.json()


async def test_a_repository_is_made_with_policies_and_shows_them(admin_client):
    await make_policy(admin_client, "old")
    await make_policy(admin_client, "any", "*")

    made = await make_repository(admin_client, cleanup_policies=["old", "any"])
    policy = (await admin_client.get(f"{POLICIES}/old")).json()

    assert made["cleanup_policies"] == ["any", "old"]
    assert policy["repositories"] == ["files2"]


async def test_a_put_without_policies_keeps_them(admin_client, sessionmaker):
    await make_policy(admin_client, "old")
    await make_repository(admin_client, cleanup_policies=["old"])

    kept = await admin_client.put(f"{REPOSITORIES}/files2", json={"online": False})
    emptied = await admin_client.put(
        f"{REPOSITORIES}/files2", json={"online": False, "cleanup_policies": []}
    )

    assert kept.json()["cleanup_policies"] == ["old"]
    assert emptied.json()["cleanup_policies"] == []
    record = await last(sessionmaker, "repository.updated")
    assert record.changes["cleanup_policies"] == {"before": ["old"], "after": []}


@pytest.mark.parametrize(
    ("repository", "policies"),
    [
        ({"format": "raw", "type": "hosted"}, ["for-npm"]),
        ({"format": "raw", "type": "hosted"}, ["nothing"]),
        ({"format": "raw", "type": "group", "group": {"members": []}}, ["old"]),
    ],
)
async def test_what_cannot_be_attached_is_refused_at_its_field(admin_client, repository, policies):
    await make_policy(admin_client, "old")
    await make_policy(admin_client, "for-npm", "npm")

    refused = await admin_client.post(
        REPOSITORIES, json={"name": "files2", **repository, "cleanup_policies": policies}
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert [detail["field"] for detail in refused.json()["error"]["details"]] == [
        "cleanup_policies"
    ]


async def test_deleting_a_policy_detaches_it_and_says_so(admin_client, sessionmaker):
    await make_policy(admin_client, "old")
    await make_repository(admin_client, cleanup_policies=["old"])

    deleted = await admin_client.delete(f"{POLICIES}/old")
    repository = (await admin_client.get(f"{REPOSITORIES}/files2")).json()

    assert deleted.status_code == 204
    assert repository["cleanup_policies"] == []
    detached = [
        record
        for record in await records(sessionmaker, "repository.updated")
        if record.target_name == "files2"
    ]
    assert [record.changes["cleanup_policies"] for record in detached] == [
        {"before": ["old"], "after": []}
    ]
    assert (await last(sessionmaker, "cleanup_policy.deleted")).target_name == "old"
