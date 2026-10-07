"""Application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
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
from megooarti.security.bootstrap import ensure_initial_admin_password
from megooarti.storage.api import router as blob_stores_router
from megooarti.system.settings_api import router as settings_router
from megooarti.system.status import router as status_router

log = structlog.get_logger(__name__)

API_PREFIX = "/api/v1"
_FIRST_START_RETRY_SECONDS = 5


async def _first_start(app: FastAPI) -> None:
    # Read app.state at call time: tests replace the sessionmaker after create_app.
    await ensure_initial_admin_password(
        app.state.sessionmaker, app.state.settings, app.state.head_revision
    )


async def _first_start_when_possible(app: FastAPI, last_error: str) -> None:
    """Keep trying until the database is reachable and migrated."""
    while True:
        await asyncio.sleep(_FIRST_START_RETRY_SECONDS)
        try:
            await _first_start(app)
            return
        except Exception as error:
            if type(error).__name__ != last_error:  # log a change of cause, not every try
                last_error = type(error).__name__
                log.warning("initial_admin_password_deferred", error=last_error)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    retry: asyncio.Task[None] | None = None
    try:
        await _first_start(app)
    except Exception as error:  # the database is not reachable or not migrated yet
        cause = type(error).__name__
        log.warning("initial_admin_password_deferred", error=cause)
        retry = asyncio.create_task(_first_start_when_possible(app, cause))
    yield
    if retry is not None:
        retry.cancel()
        with suppress(asyncio.CancelledError):
            await retry
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
    app.include_router(blob_stores_router, prefix=API_PREFIX)

    # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
    # first, so its 500 response passes through every other middleware, and keep
    # RequestIdMiddleware last, so everything else runs with a request ID.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
