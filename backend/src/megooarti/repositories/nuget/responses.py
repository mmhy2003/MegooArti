"""How a NuGet repository answers with a document it wrote: hosted or a proxy alike."""

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.repositories.content import RepositoryContext

JSON = "application/json"


async def base(context: RepositoryContext, request: Request) -> str:
    """The repository's address as a client is given it, ending in a slash."""
    return f"{await context.public_url(request)}/"


async def respond_json(context: RepositoryContext, request: Request, document: Any) -> Response:
    """A document written for this request, as JSON."""
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    return await respond_data(context, request, data)


async def respond_data(context: RepositoryContext, request: Request, data: bytes) -> Response:
    """JSON that is passed on as it is: what a remote sent, kept."""
    return await respond(context, request, data, JSON, "index.json")


async def respond(
    context: RepositoryContext, request: Request, data: bytes, content_type: str, filename: str
) -> Response:
    """A document written for this request, or passed on as a remote sent it."""
    _, changed = await context.revision()
    return context.respond_with(
        data,
        request,
        filename=filename,
        content_type=content_type,
        last_modified=changed,
        # Two changes can be made within one second: only the bytes say which a client has.
        dated=False,
    )
