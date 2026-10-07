"""Unauthenticated health endpoints for load balancers and orchestrators."""

from fastapi import APIRouter

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is running and can answer HTTP requests."""
    return {"status": "ok"}
