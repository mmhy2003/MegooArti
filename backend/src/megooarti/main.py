"""Application factory."""

from fastapi import FastAPI

from megooarti import __version__
from megooarti.config import Settings, get_settings
from megooarti.errors import register_error_handlers
from megooarti.request_id import RequestIdMiddleware
from megooarti.system.status import router as status_router

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MegooArti",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    return app
