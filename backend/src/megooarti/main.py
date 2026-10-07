"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from megooarti import __version__
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.errors import ERROR_RESPONSES, UnhandledErrorMiddleware, register_error_handlers
from megooarti.request_id import RequestIdMiddleware
from megooarti.security.api import auth as auth_api
from megooarti.security.api import me as me_api
from megooarti.security.api import roles as roles_api
from megooarti.security.api import users as users_api
from megooarti.system.settings_api import router as settings_router
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
        responses=ERROR_RESPONSES,
    )
    app.state.settings = settings
    # Creating the engine opens no connection; the pool connects on first use.
    # hide_parameters keeps bound values (tokens, password hashes) out of error text and logs.
    app.state.engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, hide_parameters=True
    )
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.head_revision = head_revision()
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    app.include_router(auth_api.router, prefix=API_PREFIX)
    app.include_router(me_api.router, prefix=API_PREFIX)
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(roles_api.router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)

    # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
    # first, so its 500 response passes through every other middleware, and keep
    # RequestIdMiddleware last, so everything else runs with a request ID.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
