"""Every route must authenticate unless it is deliberately open."""

from collections.abc import Iterator

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.security.authentication import AUTHENTICATION_DEPENDENCIES

# Routes anyone may call without credentials. Keep this list short and justified.
OPEN = {
    "/api/v1/status/live",  # health checks, required to be unauthenticated (SYS-2)
    "/api/v1/status/ready",
    "/api/v1/auth/login",  # this is where credentials are presented
}


def dependency_calls(dependant) -> set:
    found = set()
    for dependency in dependant.dependencies:
        found.add(dependency.call)
        found |= dependency_calls(dependency)
    return found


def api_routes(routes, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Every API route with its full path. Included routers are nested, not flattened."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            nested = prefix + route.include_context.prefix
            yield from api_routes(route.original_router.routes, nested)


def unguarded_routes(app: FastAPI) -> list[str]:
    return sorted(
        path
        for path, route in api_routes(app.routes)
        if path not in OPEN
        and not (dependency_calls(route.dependant) & AUTHENTICATION_DEPENDENCIES)
    )


def test_every_route_authenticates_unless_it_is_on_the_open_list(app):
    assert unguarded_routes(app) == []


def test_the_walk_finds_the_routes_of_included_routers(app):
    paths = {path for path, _ in api_routes(app.routes)}

    assert OPEN <= paths  # the open list has no stale entries
    assert {"/api/v1/users/{user_id}", "/api/v1/auth/session"} <= paths


def test_a_route_that_only_opens_a_database_session_is_reported(app):
    @app.get("/_test/forgot-to-authenticate")
    async def forgot(db: AsyncSession = Depends(get_session)) -> dict:
        return {}

    assert unguarded_routes(app) == ["/_test/forgot-to-authenticate"]
