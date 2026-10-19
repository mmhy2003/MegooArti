"""Every route must authenticate unless it is deliberately open."""

from collections.abc import Iterator

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse

from megooarti.db.session import get_session
from megooarti.security.authentication import AUTHENTICATION_DEPENDENCIES

# Routes anyone may call without credentials. Keep this list short and justified.
OPEN = {
    "/api/v1/status/live",  # health checks, required to be unauthenticated (SYS-2)
    "/api/v1/status/ready",
    "/api/v1/auth/login",  # this is where credentials are presented
    "/api/v1/auth/sources",  # the sources the sign-in screen offers, before anyone signs in
    # Sign-in at an OIDC provider: the browser is sent there, and comes back with a code.
    "/api/v1/auth/oidc/{source_id}/start",
    "/api/v1/auth/oidc/{source_id}/callback",
    # OAuth (MCP spec 7): what a client discovers is public (RFC 9728, RFC 8414); any
    # client may register (RFC 7591); authorize sends a person to the consent page, where
    # they sign in; token takes a code or a refresh token, which are the credentials.
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/token",
}
# The API description, its viewer and the files the viewer loads. They describe the
# API's shape, not its data, and are left open by design.
DOCUMENTATION = {"/api/v1/openapi.json", "/api/docs", "/api/docs/assets/{name}"}


def dependency_calls(dependant) -> set:
    found = set()
    for dependency in dependant.dependencies:
        found.add(dependency.call)
        found |= dependency_calls(dependency)
    return found


def all_routes(routes, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Every route with its full path. Included routers are nested, not flattened."""
    for route in routes:
        if hasattr(route, "original_router"):
            nested = prefix + route.include_context.prefix
            yield from all_routes(route.original_router.routes, nested)
        else:
            yield prefix + getattr(route, "path", repr(route)), route


def authenticates(route: object) -> bool:
    """Only an API route with an authentication dependency counts.

    Anything else (a mounted application, a plain or websocket route) is reported,
    because this check cannot see inside it.
    """
    if not isinstance(route, APIRoute):
        return False
    return bool(dependency_calls(route.dependant) & AUTHENTICATION_DEPENDENCIES)


def unguarded_routes(app: FastAPI) -> list[str]:
    return sorted(
        path
        for path, route in all_routes(app.routes)
        if path not in OPEN | DOCUMENTATION and not authenticates(route)
    )


def test_every_route_authenticates_unless_it_is_on_the_open_list(app):
    assert unguarded_routes(app) == []


def test_the_walk_finds_the_routes_of_included_routers(app):
    paths = {path for path, _ in all_routes(app.routes)}

    assert OPEN | DOCUMENTATION <= paths  # neither list has stale entries
    assert {"/api/v1/users/{user_id}", "/repository/{name}/{path:path}"} <= paths
    assert {"/v2/", "/v2/token", "/v2/_catalog", "/v2/{name}/{path:path}"} <= paths
    assert {"/api/v1/content", "/api/v1/content/{repository}/tree"} <= paths
    assert "/api/v1/search" in paths


def test_a_route_that_only_opens_a_database_session_is_reported(app):
    @app.get("/_test/forgot-to-authenticate")
    async def forgot(db: AsyncSession = Depends(get_session)) -> dict:
        return {}

    assert unguarded_routes(app) == ["/_test/forgot-to-authenticate"]


def test_routes_of_a_kind_the_check_does_not_understand_are_reported(app):
    async def plain(request):
        return PlainTextResponse("hello")

    async def socket(websocket):
        await websocket.close()

    app.add_route("/_test/plain", plain)
    app.add_api_websocket_route("/_test/socket", socket)
    app.mount("/_test/mounted", Starlette())

    assert unguarded_routes(app) == ["/_test/mounted", "/_test/plain", "/_test/socket"]
