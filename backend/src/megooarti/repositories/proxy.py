"""Proxy repositories: fetch from the remote on a miss, cache, and keep serving.

A missing file is downloaded completely, verified and recorded, and only then served.
Every exit that the client should remember (a cached file, a remembered miss, a
recorded failure) is committed here, because several of them end in an error response.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class Source:
    """Where a path is found when the remote's own content says so, not the path.

    A PyPI index, for one, names the address of each of its files, often on another
    host, and the hash each must have. `digests` maps an algorithm the blob store
    computes to lower-case hex.
    """

    url: str
    digests: Mapping[str, str] = field(default_factory=dict)
    # The media types to ask for, where a remote serves one address in several forms.
    accept: str | None = None
    # What the address is part of, for a remote that issues a token for each thing it
    # serves: a container image. See `remote.SignIn`.
    subject: str = ""
    # Whether a miss is remembered under the path. Not if the same path can be found
    # at another address, as a blob that several images share can.
    remember_missing: bool = True
    # Whether the remote may send the document gzipped whatever it is asked for, as
    # nuget.org sends its registrations: it is then inflated. For `ask` and `document`.
    gzipped: bool = False
    # Whether a failure counts towards leaving the remote alone. Not for a service of
    # its that is asked apart from its files, such as a search on another host: its
    # failing must not stop the files being fetched. The failure is recorded all the same.
    blocks: bool = True


@dataclass(frozen=True)
class Answer:
    """What a remote said when asked for a small document, or about one."""

    headers: Mapping[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class Absent:
    """The remote has no such thing."""


@dataclass(frozen=True)
class Unavailable:
    """The remote could not be asked, or did not help. `error` is what to answer with."""

    error: ApiError
    status: int | None = None  # what the remote answered, if it answered


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


async def _target(
    context: RepositoryContext, path: str, source: Source | None = None
) -> tuple[str, str | None]:
    """The remote URL for a path and the Authorization header to send with it."""
    settings = context.repository.config["proxy"]
    if source is not None:
        refused = remote.refusal(settings["remote_url"], source.url)
        if refused is not None:
            failed = remote.Failed(f"its index names a file's address, and {refused}", False)
            raise _unavailable(await _fail(context, path, failed))
        if not remote.same_origin(settings["remote_url"], source.url):
            # The credential is the remote's. Another host named by its content gets none.
            return source.url, None
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
    if source is not None:
        return source.url, credential
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


def _sign_in(context: RepositoryContext, source: Source | None) -> remote.SignIn | None:
    """How to sign in to this repository's remote, if its format's remotes want that."""
    if not context.format.remote_signs_in:
        return None
    remote_url = context.repository.config["proxy"]["remote_url"]
    return remote.SignIn(remote_url, "" if source is None else source.subject)


async def refuse(context: RepositoryContext, path: str, reason: str) -> ApiError:
    """Record that what the remote sent for a path cannot be used. Returns the 502 to raise.

    For a format that reads what it fetched and finds it is not what it should be.
    """
    return _unavailable(await _fail(context, path, remote.Failed(reason, blockable=False)))


async def _consult(
    context: RepositoryContext, path: str, source: Source, limit: int | None
) -> Answer | Absent | Unavailable:
    db, repository = context.db, context.repository
    now = utcnow()
    if source.remember_missing and await proxy_state.known_missing(db, repository, path, now):
        return Absent()
    if await proxy_state.blocked(db, repository, now):
        return Unavailable(_unavailable("it is blocked"))
    try:
        url, credential = await _target(context, path, source)
    except ApiError as error:  # recorded already
        return Unavailable(error)
    await db.commit()  # give the connection back while the remote is asked

    sign_in = _sign_in(context, source)
    http = context.http()
    if limit is None:
        outcome = await remote.head(
            http, url, authorization=credential, accept=source.accept, sign_in=sign_in
        )
    else:
        outcome = await remote.fetch(
            http,
            url,
            authorization=credential,
            limit=limit,
            accept=source.accept,
            sign_in=sign_in,
            gzipped=source.gzipped,
        )
    now = utcnow()
    if isinstance(outcome, remote.Exists | remote.Document):
        await proxy_state.record_success(db, repository, now)
        await db.commit()
        if isinstance(outcome, remote.Exists):
            return Answer(outcome.every)
        return Answer(outcome.headers, outcome.body)
    if isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if source.remember_missing:
            await proxy_state.remember_missing(db, repository, path, now)
        await db.commit()
        return Absent()
    if isinstance(outcome, remote.Failed) and not source.blocks:
        outcome = dataclasses.replace(outcome, blockable=False)
    reason = await _fail(context, path, outcome)
    return Unavailable(_unavailable(reason), getattr(outcome, "status", None))


async def ask(
    context: RepositoryContext, path: str, source: Source, *, limit: int
) -> Answer | Absent | Unavailable:
    """Fetch a small document from the remote into memory, for a format that reads it.

    `path` is what the document would be cached under: a miss is remembered under it,
    and a failure is recorded against it. Nothing is cached here; the caller knows
    what the document is and how to store it. The remote is not asked while it is
    blocked, and what comes of asking is recorded as for any fetch.

    This commits, before asking and after. A caller must have no uncommitted work.
    """
    return await _consult(context, normalise_path(path), source, limit)


async def probe(
    context: RepositoryContext, path: str, source: Source
) -> Answer | Absent | Unavailable:
    """Ask the remote about a path without fetching it. The answer has headers and no body.

    As `ask` in every other way.
    """
    return await _consult(context, normalise_path(path), source, None)


async def document(
    context: RepositoryContext, path: str, source: Source, *, limit: int, content_type: str
) -> bytes:
    """A small document of the remote, kept under `path` as metadata, for a format that
    reads it: what is kept while it is fresh, else what the remote has now.

    Where the remote cannot be asked, or no longer has it, what is kept is given, as for
    any cached file; with nothing kept, this raises 404 or 502. This commits.
    """
    path = normalise_path(path)
    asset = await context.get(path)
    if asset is None or not _fresh(context, asset, path):
        answer = await ask(context, path, source, limit=limit)
        if isinstance(answer, Answer):
            staged = await context.stage_bytes(answer.body)
            await context.cache(
                path, staged, content_type=content_type, attributes={}, now=utcnow()
            )
            await context.db.commit()
            return answer.body
        if asset is None:
            raise _not_found() if isinstance(answer, Absent) else answer.error
    kept = await context.read(path, limit=limit)
    if kept is None:
        raise _not_found()
    return kept


async def still_current(context: RepositoryContext, path: str) -> None:
    """Record that the remote was asked just now, and what is held is still what it has."""
    asset = await context.get(normalise_path(path))
    if asset is not None:
        asset.last_verified_at = utcnow()


async def _refresh(
    context: RepositoryContext,
    path: str,
    asset: Asset | None,
    source: Source | None = None,
    *,
    again: bool = False,
) -> None:
    """Make `path` servable from the cache, or raise 404 or 502.

    Returning without raising means there is a copy to serve: a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.
    """
    db, repository = context.db, context.repository
    now = utcnow()
    remember = source is None or source.remember_missing
    if (
        asset is None
        and remember
        and not again
        and await proxy_state.known_missing(db, repository, path, now)
    ):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        if asset is None:
            raise _unavailable("it is blocked")
        return
    url, credential = await _target(context, path, source)
    known = {} if asset is None else asset.attributes
    if asset is not None and source is not None and source.digests:
        held = await context.stat(path)
        if held is None or any(
            getattr(held, name, None) != digest for name, digest in source.digests.items()
        ):
            # What is held is not the file the index describes. Asked "has it
            # changed?", the remote could say no and leave it in place: ask for it whole.
            known = {}
    await db.commit()  # give the connection back for the length of the download

    async def stage(chunks, size: int | None) -> StagedBlob:
        return await context.stage(chunks, expected_size=size)

    outcome = await remote.download(
        context.http(),
        url,
        authorization=credential,
        stage=stage,
        etag=known.get("remote_etag"),
        last_modified=known.get("remote_last_modified"),
        accept=None if source is None else source.accept,
        sign_in=_sign_in(context, source),
    )
    now = utcnow()

    if isinstance(outcome, remote.Fetched) and source is not None:
        staged = outcome.staged
        if any(getattr(staged, name, None) != digest for name, digest in source.digests.items()):
            # Not the file the index describes. It is not kept, and not served.
            await context.discard(staged)
            outcome = remote.Failed("a file does not match the hash its index gives", False)

    if isinstance(outcome, remote.Fetched):
        origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
        described = await context.format.describe_fetched(context, path, outcome.staged)
        await context.cache(
            path,
            outcome.staged,
            content_type=context.format.content_type(path, outcome.content_type),
            attributes={**{name: value for name, value in origin.items() if value}, **described},
            component_attributes=described or None,
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
            if remember:
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


async def _head_remote(context: RepositoryContext, path: str) -> Response:
    """Answer HEAD for a file that is not cached by asking the remote. Caches nothing."""
    db, repository = context.db, context.repository
    now = utcnow()
    if await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        raise _unavailable("it is blocked")
    url, credential = await _target(context, path)
    await db.commit()

    outcome = await remote.head(
        context.http(), url, authorization=credential, sign_in=_sign_in(context, None)
    )
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


async def ensure_cached(
    context: RepositoryContext,
    path: str,
    *,
    source: Source | None = None,
    again: bool = False,
) -> None:
    """Make `path` servable from this proxy's cache, or raise 404 or 502.

    Returning means there is a copy to serve: a fresh one, a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.

    `source` says where the path is found when the remote's own content names the
    address. The remote's credential then goes only to the remote's own origin, an
    internal address is refused unless the remote is at that host, and content that
    does not match the hashes given is not cached. With `again`, the remote is asked
    however new the copy, and whatever it said of the path before.

    This commits: before waiting for a download, and to record what came of it. A
    caller must have no uncommitted work of its own when it calls this.
    """
    path = normalise_path(path)
    asset = await context.get(path)
    if not again and _fresh(context, asset, path):
        return
    await context.db.commit()  # hold no connection while waiting for another's download
    async with _downloads.hold((context.repository.id, path)):
        asset = await context.get(path, fresh=True)  # the previous holder may have fetched it
        if again or not _fresh(context, asset, path):
            await _refresh(context, path, asset, source, again=again)


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
    if request.method == "HEAD" and await context.get(path) is None:
        return await _head_remote(context, path)
    await ensure_cached(context, path)
    return await context.respond(path, request)
