from datetime import UTC, datetime

import pytest

from megooarti.security.models import User

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def dana(db) -> User:
    user = User(username="dana", display_name="Dana")
    db.add(user)
    await db.flush()
    return user
