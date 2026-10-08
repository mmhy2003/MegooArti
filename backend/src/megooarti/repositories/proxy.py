"""Proxy repositories: fetch from the remote on a miss, cache, and keep serving.

A missing file is downloaded completely, verified and recorded, and only then served.
Every exit that the client should remember (a cached file, a remembered miss, a
recorded failure) is committed here, because several of them end in an error response.
"""

from datetime import datetime, timedelta
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.keyed_locks import KeyedLocks
from megooarti.repositories import proxy_state, remote
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset
from megooarti.repositories.paths import normalise_path
from megooarti.secrets_box import SecretUnreadable
from megooarti.storage.backends import StagedBlob

log = structlog.get_logger(__name__)

# Within this process, concurrent requests for one uncached path share one download.
_downloads = KeyedLocks()


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


def _unavailable(reason: str) -> ApiError:
    return ApiError(502, "remote_unavailable", f"The remote repository is not available: {reason}.")


def is_fresh(
    settings: dict[str, Any], format: Format, asset: Asset, path: str, now: datetime
) -> bool:
    """Whether a cached file may be served without asking the remote."""
    if asset.last_verified_at is None:
        return False
    kind = "metadata" if format.is_metadata(path) else "content"
    minutes = settings[f"{kind}_max_age_minutes"]
    return minutes < 0 or now - asset.last_verified_at < timedelta(minutes=minutes)


def _fresh(context: RepositoryContext, asset: Asset | None, path: str) -> bool:
    if asset is None:
        return False
    settings = context.repository.config["proxy"]
    return is_fresh(settings, context.format, asset, path, utcnow())


async def _target(context: RepositoryContext, path: str) -> tuple[str, str | None]:
    """The remote URL for a path and the Authorization header to send with it."""
    settings = context.repository.config["proxy"]
    try:
        credential = remote.authorization(context.settings, settings["remote_auth"])
    except SecretUnreadable:
        # Recorded and logged, not only raised: behind a group this 502 becomes a 404,
        # and the repository's status is then the only place the cause can be seen.
        unreadable = remote.Failed(
            "its stored credential cannot be read with the current key; enter it again",
            blockable=False,
        )
        raise _unavailable(await _fail(context, path, unreadable)) from None
    return context.format.remote_url(settings["remote_url"], path), credential


async def _fail(context: RepositoryContext, path: str, outcome: object) -> str:
    """Record that the remote did not help. Returns the reason, for the caller to use."""
    if isinstance(outcome, remote.Failed):
        reason, blockable = outcome.reason, outcome.blockable
    else:
        reason, blockable = "it gave an answer that makes no sense here", False
    await proxy_state.record_failure(
        context.db, context.repository, utcnow(), reason, blockable=blockable
    )
    await context.db.commit()
    log.warning("remote_failed", repository=context.repository.name, path=path, reason=reason)
    return reason


async def _refresh(
    context: RepositoryContext, request: Request, path: str, asset: Asset | None
) -> None:
    """Make `path` servable from the cache, or raise 404 or 502.

    Returning without raising means there is a copy to serve: a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.
    """
    db, repository = context.db, context.repository
    now = utcnow()
    if asset is None and await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        if asset is None:
            raise _unavailable("it is blocked")
        return
    url, credential = await _target(context, path)
    known = {} if asset is None else asset.attributes
    await db.commit()  # give the connection back for the length of the download

    async def stage(chunks, size: int | None) -> StagedBlob:
        return await context.stage(chunks, expected_size=size)

    outcome = await remote.download(
        remote.client_of(request.app),
        url,
        authorization=credential,
        stage=stage,
        etag=known.get("remote_etag"),
        last_modified=known.get("remote_last_modified"),
    )
    now = utcnow()

    if isinstance(outcome, remote.Fetched):
        origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
        await context.cache(
            path,
            outcome.staged,
            content_type=outcome.content_type,
            attributes={name: value for name, value in origin.items() if value},
            now=now,
        )
        await proxy_state.record_success(db, repository, now)
        await db.commit()
    elif isinstance(outcome, remote.NotModified) and asset is not None:
        asset.last_verified_at = now
        await proxy_state.record_success(db, repository, now)
        await db.commit()
    elif isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if asset is None:
            await proxy_state.remember_missing(db, repository, path, now)
            await db.commit()
            raise _not_found()
        # The remote dropped a file we hold. An artifact manager keeps it.
        asset.last_verified_at = now
        await db.commit()
    else:
        reason = await _fail(context, path, outcome)
        if asset is None:
            raise _unavailable(reason)


async def _head_remote(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer HEAD for a file that is not cached by asking the remote. Caches nothing."""
    db, repository = context.db, context.repository
    now = utcnow()
    if await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        raise _unavailable("it is blocked")
    url, credential = await _target(context, path)
    await db.commit()

    outcome = await remote.head(remote.client_of(request.app), url, authorization=credential)
    now = utcnow()
    if isinstance(outcome, remote.Exists):
        await proxy_state.record_success(db, repository, now)
        await db.commit()
        headers = {**outcome.headers, "X-Content-Type-Options": "nosniff"}
        return Response(status_code=200, headers=headers)
    if isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)
        await proxy_state.remember_missing(db, repository, path, now)
        await db.commit()
        raise _not_found()
    raise _unavailable(await _fail(context, path, outcome))


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a proxy repository. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    asset = await context.get(path)
    if _fresh(context, asset, path):
        return await context.respond(path, request)
    if asset is None and request.method == "HEAD":
        return await _head_remote(context, request, path)

    await context.db.commit()  # hold no connection while waiting for another's download
    async with _downloads.hold((context.repository.id, path)):
        asset = await context.get(path, fresh=True)  # the previous holder may have fetched it
        if not _fresh(context, asset, path):
            await _refresh(context, request, path, asset)
    return await context.respond(path, request)
