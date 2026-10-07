"""Database sessions for request handlers."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False keeps loaded objects usable after a commit, which async code
    # needs because it cannot lazily reload them.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session for one request. It does not commit: the code that changes data does.

    Anything not committed is rolled back when the session closes.
    """
    async with request.app.state.sessionmaker() as session:
        yield session
