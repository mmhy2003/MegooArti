"""Send a request for repository content to the engine for the repository's type.

An engine answers for one type of repository. It does not authenticate, authorise
`read`, or commit: the route does those around it.
"""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.proxy import handle_proxy

Engine = Callable[[RepositoryContext, Request, str], Awaitable[Response]]


async def _hosted(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_hosted(context, request, path)


ENGINES: dict[str, Engine] = {"hosted": _hosted, "proxy": handle_proxy}


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    engine = ENGINES.get(context.repository.type)
    if engine is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return await engine(context, request, path)
