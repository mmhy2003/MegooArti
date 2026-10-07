"""Unauthenticated health endpoints for load balancers and orchestrators."""

import asyncio

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from megooarti.db.schema import current_revision

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/status", tags=["status"])

READINESS_TIMEOUT_SECONDS = 5


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is running and can answer HTTP requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """The process can reach its database and the schema matches this version."""
    checks = {"database": "ok", "schema": "ok"}
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with request.app.state.engine.connect() as connection:
                revision = await current_revision(connection)
    except Exception as error:  # any driver, network or timeout failure means "not ready"
        log.warning("readiness_database_unreachable", error=type(error).__name__)
        checks = {"database": "unreachable", "schema": "unknown"}
    else:
        expected = request.app.state.head_revision
        if revision != expected:
            log.warning("readiness_schema_out_of_date", found=revision, expected=expected)
            checks["schema"] = "out_of_date"

    healthy = all(result == "ok" for result in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status_code=200 if healthy else 503,
    )
