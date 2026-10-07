"""The administrator guard under real, concurrent transactions.

The other tests share one connection, which cannot show two requests racing. This
test is synchronous and drives its own event loop, like the migration tests.
"""

import asyncio

import pytest
from alembic import command
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.db.schema import alembic_config
from megooarti.errors import ApiError
from megooarti.security import roles
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import User, UserRole


def test_two_administrators_cannot_demote_each_other_at_the_same_time(empty_database):
    command.upgrade(alembic_config(empty_database), "head")

    async def scenario() -> None:
        engine = create_async_engine(empty_database, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as setup:
                admin_role = await roles.get_role(setup, "admin")
                user_ids = []
                for name in ("ada", "bob"):
                    user = User(username=name, display_name=name, password_hash="hash")
                    setup.add(user)
                    await setup.flush()
                    await setup.execute(
                        insert(UserRole).values(user_id=user.id, role_id=admin_role.id)
                    )
                    user_ids.append(user.id)
                await setup.commit()
            ada, bob = user_ids

            async with factory() as first, factory() as second:
                await first.execute(delete(UserRole).where(UserRole.user_id == bob))
                await second.execute(delete(UserRole).where(UserRole.user_id == ada))

                await ensure_administrator_remains(first)
                waiting = asyncio.create_task(ensure_administrator_remains(second))
                finished, _ = await asyncio.wait({waiting}, timeout=1)
                assert not finished, "the second change was checked without waiting for the first"

                await first.commit()
                with pytest.raises(ApiError) as caught:
                    await waiting
                assert caught.value.code == "last_administrator"
        finally:
            await engine.dispose()

    asyncio.run(scenario())
