"""Application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from megooarti import __version__
from megooarti.api_docs import docs_router
from megooarti.clock import utcnow
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.errors import ERROR_RESPONSES, UnhandledErrorMiddleware, register_error_handlers
from megooarti.maintenance import run_exclusively, run_periodically
from megooarti.mcp.endpoint import router as mcp_router
from megooarti.mcp.server import Server as McpServer
from megooarti.proxies import ProxiesMiddleware, networks
from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
from megooarti.repositories import remote, upkeep
from megooarti.repositories.api import router as repositories_router
from megooarti.repositories.apk import format as _apk_format  # noqa: F401  (registers it)
from megooarti.repositories.apt import format as _apt_format  # noqa: F401  (registers it)
from megooarti.repositories.content_api import router as content_api_router
from megooarti.repositories.docker.routes import router as registry_router  # registers the format
from megooarti.repositories.formats_api import router as formats_router
from megooarti.repositories.maven import format as _maven_format  # noqa: F401  (registers it)
from megooarti.repositories.npm import format as _npm_format  # noqa: F401  (registers it)
from megooarti.repositories.nuget import format as _nuget_format  # noqa: F401  (registers it)
from megooarti.repositories.pypi import format as _pypi_format  # noqa: F401  (registers it)
from megooarti.repositories.routes import router as content_router
from megooarti.repositories.search_api import router as search_router
from megooarti.repositories.yum import format as _yum_format  # noqa: F401  (registers it)
from megooarti.request_id import RequestIdMiddleware
from megooarti.security import directory_check, oauth
from megooarti.security import header as _header  # noqa: F401  (registers the kind of source)
from megooarti.security import ldap as _ldap  # noqa: F401  (registers the kind of source)
from megooarti.security import oidc as _oidc  # noqa: F401  (registers the kind of source)
from megooarti.security.api import auth as auth_api
from megooarti.security.api import me as me_api
from megooarti.security.api import oauth as oauth_api
from megooarti.security.api import oidc as oidc_api
from megooarti.security.api import roles as roles_api
from megooarti.security.api import sources as sources_api
from megooarti.security.api import users as users_api
from megooarti.security.bootstrap import ensure_initial_admin_password
from megooarti.storage import blobs
from megooarti.storage.api import router as blob_stores_router
from megooarti.system import certificates
from megooarti.system.certificates_api import router as certificates_router
from megooarti.system.information_api import router as information_router
from megooarti.system.settings_api import router as settings_router
from megooarti.system.settings_store import get_setting
from megooarti.system.status import router as status_router

log = structlog.get_logger(__name__)

API_PREFIX = "/api/v1"
_FIRST_START_RETRY_SECONDS = 5
# Arbitrary constant, distinct from the other advisory lock keys.
_COMPACTION_LOCK_KEY = 0x4D45474F51


async def _first_start(app: FastAPI) -> None:
    # Read app.state at call time: tests replace the sessionmaker after create_app.
    await ensure_initial_admin_password(
        app.state.sessionmaker, app.state.settings, app.state.head_revision
    )
    async with app.state.sessionmaker() as db:
        remote.trust(app, await certificates.trusted_pems(db))  # before anything goes out
        app.state.trusted_proxies = networks(await get_setting(db, "trusted_proxies"))


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


async def _compact(app: FastAPI) -> None:
    settings = app.state.settings

    async def job() -> None:
        async with app.state.sessionmaker() as db:
            await oauth.forget(db, utcnow())  # OAuth's codes, tokens and approvals that ended
            await db.commit()
        # First, so that what upkeep removes starts its wait for compaction now.
        await upkeep.run(app.state.sessionmaker, settings, utcnow())
        removed = await blobs.compact(
            app.state.sessionmaker,
            settings,
            now=utcnow(),
            grace_seconds=settings.blob_grace_seconds,
        )
        log.info("compaction_finished", removed=removed)

    await run_exclusively(app.state.engine, _COMPACTION_LOCK_KEY, job)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    background: list[asyncio.Task[None]] = []
    try:
        await _first_start(app)
    except Exception as error:  # the database is not reachable or not migrated yet
        cause = type(error).__name__
        log.warning("initial_admin_password_deferred", error=cause)
        background.append(asyncio.create_task(_first_start_when_possible(app, cause)))
    # LDAP users no longer in their directory are disabled (spec 7, D4), by one container.
    background.append(
        asyncio.create_task(
            run_periodically(
                "directory_check",
                directory_check.CHECK_SECONDS,
                lambda: run_exclusively(
                    app.state.engine, directory_check.LOCK_KEY, lambda: directory_check.run(app)
                ),
            )
        )
    )
    if settings.compaction_interval_seconds > 0:
        background.append(
            asyncio.create_task(
                run_periodically(
                    "compaction", settings.compaction_interval_seconds, lambda: _compact(app)
                )
            )
        )
    yield
    for task in background:
        task.cancel()
    for task in background:
        with suppress(asyncio.CancelledError):
            await task
    await remote.close_clients(app)
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MegooArti",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None,  # served by api_docs, with its own files
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
    app.state.started_at = utcnow()
    # The one client for requests to proxy remotes. Tests replace it with a fake remote.
    app.state.http = None  # built by remote.client_of on first use: it is slow to create
    # What outbound TLS trusts besides the usual authorities: read from the database at
    # start, and changed with the certificates (spec 6).
    app.state.trusted_certificates = []
    app.state.tls = None
    app.state.retired = []  # clients replaced, closed at shutdown: their requests may be long
    # One change of what is trusted at a time: its list is read and given as it was kept.
    app.state.trust_lock = asyncio.Lock()
    # The proxies an administrator trusts in front of the gateway (spec 8): read at start,
    # and changed with the setting.
    app.state.trusted_proxies = []
    register_error_handlers(app)
    app.include_router(docs_router(f"{API_PREFIX}/openapi.json", "MegooArti API"))
    app.include_router(status_router, prefix=API_PREFIX)
    app.include_router(auth_api.router, prefix=API_PREFIX)
    app.include_router(oidc_api.router, prefix=API_PREFIX)  # sign-in at an OIDC provider
    app.include_router(me_api.router, prefix=API_PREFIX)
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(roles_api.router, prefix=API_PREFIX)
    app.include_router(sources_api.router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)
    app.include_router(information_router, prefix=API_PREFIX)
    app.include_router(certificates_router, prefix=API_PREFIX)
    app.include_router(blob_stores_router, prefix=API_PREFIX)
    app.include_router(repositories_router, prefix=API_PREFIX)
    app.include_router(content_api_router, prefix=API_PREFIX)
    app.include_router(search_router, prefix=API_PREFIX)
    app.include_router(formats_router, prefix=API_PREFIX)
    app.include_router(content_router)  # /repository/..., outside the JSON API
    app.include_router(registry_router)  # /v2/..., the container registry API
    app.state.mcp = McpServer()
    app.include_router(mcp_router)  # /mcp, for AI agents
    app.include_router(oauth_api.well_known)  # /.well-known/..., how agents sign in
    app.include_router(oauth_api.endpoints)  # /oauth/..., where they do
    app.include_router(oauth_api.consent, prefix=API_PREFIX)  # the consent page's

    # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
    # first, so its 500 response passes through every other middleware, and keep
    # RequestIdMiddleware last, so everything else runs with a request ID.
    app.add_middleware(UnhandledErrorMiddleware)
    # Who a request comes from, before anything reads it.
    app.add_middleware(
        ProxiesMiddleware,
        deployment=settings.forwarded_allow_ips,
        proxies=lambda: app.state.trusted_proxies,
    )
    app.add_middleware(RequestIdMiddleware)
    return app
