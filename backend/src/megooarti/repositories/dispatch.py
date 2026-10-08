"""Send a request for repository content to the engine for the repository's type.

An engine answers for one type of repository, through the format's hook for that type,
so a format can answer some paths itself and leave the rest to the generic engine. An
engine does not authenticate, authorise `read`, or commit: the route does those.
"""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext

Engine = Callable[[RepositoryContext, Request, str], Awaitable[Response]]


async def _hosted(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_hosted(context, request, path)


async def _proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_proxy(context, request, path)


async def _group(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_group(context, request, path, serve)


ENGINES: dict[str, Engine] = {"hosted": _hosted, "proxy": _proxy, "group": _group}


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    engine = ENGINES.get(context.repository.type)
    if engine is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return await engine(context, request, path)
