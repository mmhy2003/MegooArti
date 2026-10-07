"""Requests for repository content: /repository/{name}/{path}.

Authentication and the `read` check happen here, before any format code runs. The
storage facade checks `add`, `edit` and `delete` at the moment of each operation.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import get_format
from megooarti.security.authentication import (
    Principal,
    authorize,
    client_principal,
    unauthorized,
)
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore

log = structlog.get_logger(__name__)

router = APIRouter()

_METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]


@router.api_route("/repository/{name}/{path:path}", methods=_METHODS, include_in_schema=False)
async def repository_content(
    name: str,
    path: str,
    request: Request,
    principal: Principal | None = Depends(client_principal),
    db: AsyncSession = Depends(get_session),
) -> Response:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    settings = request.app.state.settings
    store = await db.get(BlobStore, repository.blob_store_id)
    context = RepositoryContext(
        db=db,
        settings=settings,
        repository=repository,
        principal=principal,
        format=get_format(repository.format),
        backend=backend_for(settings, store),
    )

    if request.method in ("GET", "HEAD"):
        authorize(principal, context.permission("read"), scheme="Basic")
    elif principal is None:
        raise unauthorized(scheme="Basic")
    if not repository.online:
        raise ApiError(503, "repository_offline", "This repository is offline.")

    try:
        response = await context.format.handle_hosted(context, request, path)
        # Committing here, not in each format, means a format cannot answer "stored"
        # for a change that was never committed.
        await db.commit()
        return response
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was stored; nobody is left to answer.
        log.info("upload_interrupted", repository=name, path=path)
        return Response(status_code=400)
