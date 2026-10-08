"""Requests for repository content: /repository/{name}/{path}.

Authentication and the `read` check happen here, before any format or engine code runs.
The storage facade checks `add`, `edit` and `delete` at the moment of each operation.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.repositories import dispatch, remote, service
from megooarti.repositories.content import build_context
from megooarti.repositories.formats import get_format
from megooarti.security.authentication import (
    Principal,
    authorize,
    client_credentials,
    unauthorized,
)

log = structlog.get_logger(__name__)

router = APIRouter()

_METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]


@router.api_route("/repository/{name}/{path:path}", methods=_METHODS, include_in_schema=False)
async def repository_content(
    name: str,
    path: str,
    request: Request,
    credentials: Principal | ApiError | None = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    repository = await service.get_repository(db, name)
    handler = None if repository is None else get_format(repository.format)
    reading = request.method in ("GET", "HEAD")
    in_body = (
        handler is not None and not reading and handler.takes_body_credentials(request.method, path)
    )
    if in_body:
        # This request carries its credentials in its body, and the format checks them.
        # Whatever a header carries is not looked at, valid or not: a client whose
        # saved token was revoked sends it with every request, the next sign-in too.
        principal = None
    elif isinstance(credentials, ApiError):
        raise credentials
    else:
        principal = credentials
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    context = await build_context(
        db,
        request.app.state.settings,
        repository,
        principal,
        # Built on first use: most requests never reach a remote.
        outbound=lambda: remote.client_of(request.app),
    )

    if reading:
        authorize(principal, context.permission("read"), scheme="Basic")
    elif principal is None and not in_body:
        raise unauthorized(scheme="Basic")
    if not repository.online:
        raise ApiError(503, "repository_offline", "This repository is offline.")

    try:
        response = await dispatch.serve(context, request, path)
        # Committing here, not in each format or engine, means none of them can answer
        # "stored" for a change that was never committed.
        await db.commit()
        return response
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was stored; nobody is left to answer.
        log.info("upload_interrupted", repository=name, path=path)
        return Response(status_code=400)
