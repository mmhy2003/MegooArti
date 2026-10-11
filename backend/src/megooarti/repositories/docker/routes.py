"""The container registry API, at `/v2/`.

Container clients only speak to `/v2/` at a host's root, so this is where Docker
repositories are served, all of them: the first part of an image's name is the
repository. Who is asking and whether they may read are decided here, before any
format code runs, as on the content route. What differs is the shape of an error and
the way a client is asked to sign in.
"""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.repositories import dispatch, remote, service
from megooarti.repositories.content import build_context
from megooarti.repositories.docker import errors, names
from megooarti.repositories.docker.errors import RegistryError
from megooarti.repositories.docker.format import FORMAT, images
from megooarti.security import registry_tokens
from megooarti.security.authentication import (
    Credentials,
    Principal,
    authorize,
    client_credentials,
    issue_registry_token,
)
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

router = APIRouter()

_METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]
_CATALOG_DEFAULT = 100
_CATALOG_MOST = 1000


def _unauthorized(message: str = "Authentication is required.") -> RegistryError:
    return RegistryError(401, "UNAUTHORIZED", message)


async def _challenge(request: Request, db: AsyncSession, scope: str | None) -> str:
    """How a client is told to sign in: where to fetch a registry token, and for what."""
    base = await get_setting(db, "base_url") or str(request.base_url)
    realm = f"{base.rstrip('/')}/v2/token"
    service_name = request.headers.get("Host", "registry")
    challenge = f'Bearer realm="{realm}",service="{service_name}"'
    return challenge if scope is None else f'{challenge},scope="{scope}"'


async def _answer(
    request: Request,
    db: AsyncSession,
    work: Callable[[], Awaitable[Response]],
    *,
    scope: str | None = None,
) -> Response:
    """Run a registry request, and put whatever goes wrong in the registry's shape."""
    try:
        response = await work()
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was kept; nobody is left to answer.
        log.info("upload_interrupted", path=request.url.path)
        return Response(status_code=400)
    except ApiError as error:
        await db.rollback()
        headers = {}
        if error.status_code == 401:
            headers["WWW-Authenticate"] = await _challenge(request, db, scope)
        return errors.response(error, headers)
    response.headers.update(errors.API_VERSION)
    return response


async def _caller(request: Request, credentials: Credentials) -> Principal:
    """Who is asking. A registry request always says so: there is no falling back.

    Without credentials the answer is the challenge, even while anonymous access is
    on: a client then fetches a registry token for the anonymous user, which is how
    it learns that it may.
    """
    if "Authorization" not in request.headers:
        raise _unauthorized()
    principal = await credentials.principal()
    if principal is None:
        raise _unauthorized()
    return principal


@router.get("/v2/", include_in_schema=False)
async def base(
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Is this a registry, and am I signed in?"""

    async def work() -> Response:
        await _caller(request, credentials)
        return JSONResponse({})

    return await _answer(request, db, work)


@router.get("/v2/token", include_in_schema=False)
async def token(
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Sign in: a user name and a password or API token in, a registry token out.

    Without credentials the token is the anonymous user's, if anonymous access is on.
    """
    try:
        signed_in = "Authorization" in request.headers
        principal = await credentials.principal() if signed_in else None
        value = await issue_registry_token(request, db, principal)
        await db.commit()
    except ApiError as error:
        await db.rollback()
        headers = (
            {"WWW-Authenticate": 'Basic realm="MegooArti"'} if error.status_code == 401 else {}
        )
        return errors.response(error, headers)
    now = utcnow()
    body = {
        "token": value,
        "access_token": value,
        "expires_in": registry_tokens.LIFETIME_SECONDS,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store", **errors.API_VERSION})


def _paging(request: Request) -> tuple[int, str]:
    asked = request.query_params.get("n", "")
    plain = asked.isascii() and asked.isdigit() and len(asked) <= 6
    count = min(int(asked), _CATALOG_MOST) if plain else _CATALOG_DEFAULT
    return count, request.query_params.get("last", "")


@router.get("/v2/_catalog", include_in_schema=False)
async def catalog(
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """The images the caller may read, in every Docker repository."""

    async def work() -> Response:
        principal = await _caller(request, credentials)
        count, last = _paging(request)
        found: list[str] = []
        for repository in await service.repositories_of(db, FORMAT):
            context = await build_context(db, request.app.state.settings, repository, principal)
            if not repository.online or not principal.allows(context.permission("read")):
                continue
            found.extend(f"{repository.name}/{image}" for image in await images(context))
        listed = sorted(name for name in found if name > last)
        page = listed[:count]
        headers = {}
        if count and len(listed) > count:
            headers["Link"] = f'</v2/_catalog?n={count}&last={page[-1]}>; rel="next"'
        await db.commit()
        return JSONResponse({"repositories": page}, headers=headers)

    return await _answer(request, db, work, scope="registry:catalog:*")


def _scope(name: str, path: str, method: str) -> str | None:
    """What a client should ask a token for, so that this request would be allowed."""
    image = names.classify(path).image
    if not image:
        return None
    actions = "pull" if method in ("GET", "HEAD") else "pull,push"
    return f"repository:{name}/{image}:{actions}"


@router.api_route("/v2/{name}/{path:path}", methods=_METHODS, include_in_schema=False)
async def repository_request(
    name: str,
    path: str,
    request: Request,
    credentials: Credentials = Depends(client_credentials),
    db: AsyncSession = Depends(get_session),
) -> Response:
    async def work() -> Response:
        principal = await _caller(request, credentials)
        repository = await service.get_repository(db, name)
        if repository is None or repository.format != FORMAT:
            raise RegistryError(404, "NAME_UNKNOWN", "No such repository.")
        if len(name) + 1 + len(names.classify(path).image) > names.MAX_NAME_LENGTH:
            raise RegistryError(400, "NAME_INVALID", "The image's name is too long.")
        context = await build_context(
            db,
            request.app.state.settings,
            repository,
            principal,
            # Built on first use: most requests never reach a remote.
            outbound=lambda: remote.client_of(request.app),
        )
        if request.method in ("GET", "HEAD"):
            authorize(principal, context.permission("read"), scheme="Basic")
        if not repository.online:
            raise ApiError(503, "repository_offline", "This repository is offline.")
        response = await dispatch.serve(context, request, path)
        # Committing here, not in the format, means it cannot answer "stored" for a
        # change that was never committed.
        await db.commit()
        return response

    return await _answer(request, db, work, scope=_scope(name, path, request.method))
