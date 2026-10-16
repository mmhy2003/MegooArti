"""A proxy of a V3 feed: nuget.org, or any feed that serves NuGet's V3 protocol.

The remote's service index says where it serves each resource, often on other hosts
(nuget.org searches elsewhere). It is kept as metadata, under a path no client asks
for. The proxy serves a service index of its own, with its own addresses.

A package and its `.nuspec` are cached files, kept as every proxy keeps its files; an
id's versions and its registration are metadata, kept and asked about again after the
proxy's metadata age; search and autocomplete are passed on every time. What the proxy
passes on of a registration or a search has the remote's addresses made its own, as it
is sent: what is kept is what the remote sent.
"""

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import documents, paths, remotes, responses
from megooarti.repositories.proxy import Absent, Answer, Source

# Where the remote's service index is kept: a path no client asks for.
REMOTE_INDEX = ".remote/index.json"
# What is read of the remote's documents, at the most.
INDEX_MOST = 1024 * 1024
REGISTRATION_MOST = 32 * 1024 * 1024
SEARCH_MOST = 8 * 1024 * 1024


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Nothing is served at this address.")


async def resources(context: RepositoryContext) -> remotes.Resources:
    """Where the remote serves what the proxy passes on. Raises 502 for an index that
    cannot be used, as for a remote that cannot be reached."""
    remote_url = context.repository.config["proxy"]["remote_url"]
    data = await proxy.document(
        context, REMOTE_INDEX, Source(remote_url), limit=INDEX_MOST, content_type=responses.JSON
    )
    try:
        return remotes.read_index(data)
    except remotes.InvalidIndex as error:
        raise await proxy.refuse(context, REMOTE_INDEX, str(error)) from None


def _replacements(found: remotes.Resources, base: str) -> list[tuple[str, str]]:
    """The remote's addresses and the proxy's for them, the longest first."""
    pairs = [(registration, f"{base}{paths.REGISTRATION}") for registration in found.registrations]
    pairs.append((found.packages, f"{base}{paths.PACKAGES}"))
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _relative(path: str, prefix: str) -> str | None:
    """What follows a resource's address in a path, or None if nothing does."""
    rest = path[len(prefix) :] if path.startswith(prefix) else ""
    return rest or None


async def _parsed(context: RepositoryContext, path: str, data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        raise await proxy.refuse(context, path, "it sent a document that is not JSON") from None


async def _registration(
    context: RepositoryContext, request: Request, path: str, relative: str
) -> Response:
    found = await resources(context)
    data = await proxy.document(
        context,
        path,
        Source(f"{found.registration}{relative}", gzipped=True),
        limit=REGISTRATION_MOST,
        content_type=responses.JSON,
    )
    base = await responses.base(context, request)
    document = remotes.rewrite(await _parsed(context, path, data), _replacements(found, base))
    return await responses.respond_json(context, request, document)


async def _passed_on(context: RepositoryContext, request: Request, path: str) -> Response:
    """A search or an autocomplete, passed on as it came, its answer not kept."""
    found = await resources(context)
    address = found.search if path == paths.SEARCH else found.autocomplete
    if not address:
        raise _not_found()
    query = request.url.query
    source = Source(f"{address}?{query}" if query else address, remember_missing=False)
    answer = await proxy.ask(context, path, source, limit=SEARCH_MOST)
    if isinstance(answer, Absent):
        raise _not_found()
    if not isinstance(answer, Answer):
        raise answer.error
    base = await responses.base(context, request)
    document = remotes.rewrite(
        await _parsed(context, path, answer.body), _replacements(found, base)
    )
    return await responses.respond_json(context, request, document)


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a V3 proxy. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    if path == paths.SERVICE_INDEX:
        found = await resources(context)
        index = documents.service_index(
            await responses.base(context, request),
            publish=False,
            search=bool(found.search),
            autocomplete=bool(found.autocomplete),
        )
        return await responses.respond_json(context, request, index)
    if (relative := _relative(path, paths.PACKAGES)) is not None:
        found = await resources(context)
        await proxy.ensure_cached(context, path, source=Source(f"{found.packages}{relative}"))
        return await context.respond(path, request)
    if (relative := _relative(path, paths.REGISTRATION)) is not None and path.endswith(".json"):
        return await _registration(context, request, path, relative)
    if path in (paths.SEARCH, paths.AUTOCOMPLETE):
        return await _passed_on(context, request, path)
    raise _not_found()
