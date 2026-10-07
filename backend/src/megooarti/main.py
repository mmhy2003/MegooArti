"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from megooarti import __version__
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.errors import register_error_handlers
from megooarti.request_id import RequestIdMiddleware
from megooarti.system.status import router as status_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MegooArti",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    # Creating the engine opens no connection; the pool connects on first use.
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.head_revision = head_revision()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    return app
