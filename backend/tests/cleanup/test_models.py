"""Cleanup policies and what they are attached to, as kept (spec 4.1)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from megooarti.cleanup.criteria import Criteria
from megooarti.cleanup.models import CleanupPolicy, RepositoryCleanupPolicy
from megooarti.clock import utcnow
from megooarti.repositories import service


def policy(name: str = "old", **criteria) -> CleanupPolicy:
    return CleanupPolicy(
        name=name, name_key=name.lower(), format="raw", **(criteria or {"updated_days": 30})
    )


async def attached(db) -> list[RepositoryCleanupPolicy]:
    return list(await db.scalars(select(RepositoryCleanupPolicy)))


async def test_an_attachment_goes_with_its_repository(db, files):
    kept = policy()
    db.add(kept)
    await db.flush()
    db.add(RepositoryCleanupPolicy(repository_id=files.id, policy_id=kept.id))
    await db.commit()

    await service.delete_repository(db, files, utcnow())
    await db.commit()

    assert await attached(db) == []
    assert await db.get(CleanupPolicy, kept.id) is not None


async def test_an_attachment_goes_with_its_policy(db, files):
    kept = policy()
    db.add(kept)
    await db.flush()
    db.add(RepositoryCleanupPolicy(repository_id=files.id, policy_id=kept.id))
    await db.commit()

    await db.delete(kept)
    await db.commit()

    assert await attached(db) == []
    assert await service.describe(db, files) is not None


async def test_two_policies_are_not_named_alike_whatever_the_case(db):
    db.add(policy("old"))
    await db.flush()
    db.add(policy("OLD"))

    with pytest.raises(IntegrityError):
        await db.flush()


def test_a_policy_says_its_criteria():
    kept = policy(updated_days=30, release_type="prerelease")

    assert kept.criteria == Criteria(updated_days=30, release_type="prerelease")
