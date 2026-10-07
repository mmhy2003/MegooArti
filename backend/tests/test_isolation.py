import pytest
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.system.models import SystemSetting


async def count_settings(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(SystemSetting))


@pytest.mark.parametrize("round_number", [1, 2])
async def test_rows_written_in_one_test_are_gone_in_the_next(db, round_number):
    assert await count_settings(db) == 0

    db.add(SystemSetting(key="probe", value={"round": round_number}))
    await db.commit()

    assert await count_settings(db) == 1


async def test_the_application_sees_rows_the_test_committed(app, client, db):
    @app.get("/_test/probe")
    async def probe(session: AsyncSession = Depends(get_session)) -> dict:
        row = await session.get(SystemSetting, "probe")
        return {"value": None if row is None else row.value}

    db.add(SystemSetting(key="probe", value={"seen": True}))
    await db.commit()

    response = await client.get("/_test/probe")

    assert response.json() == {"value": {"seen": True}}
