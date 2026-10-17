"""A group of NuGet repositories: one V3 feed of its members' (spec 7.1, 7.2).

An id's versions are the union of its members'; its registration is the group's own,
written from its members' items, the first member's for a version several have; a
search and an autocomplete are merged in the members' order. Each is written on each
request from what the members have, each member keeping what it keeps (W1). A package,
its `.nuspec` and a file of NuGet Audit's come from the first member that has them, as
the generic group engine answers. A group signs and checks nothing (E4).
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import group
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import Serve
from megooarti.repositories.nuget import (
    documents,
    feeds,
    grouped_v2,
    paths,
    proxied,
    responses,
)


def _not_found(message: str = "No member of this group has it.") -> ApiError:
    return ApiError(404, "not_found", message)


async def _registration(
    context: RepositoryContext, request: Request, parsed: paths.NuGetPath, base: str
) -> Response:
    items = await feeds.items_of(context, request, parsed.id, base)
    if not items:
        raise _not_found()
    if parsed.kind == "registration":
        document = documents.merged_registration(base, parsed.id, items)
    elif parsed.kind == "page":
        document = documents.merged_page(base, parsed.id, items, parsed.lower, parsed.upper)
    else:
        chosen = [one for one in items if documents.version_of(one) == parsed.version]
        document = documents.merged_leaf(base, parsed.id, chosen[0]) if chosen else None
    if document is None:
        raise _not_found()
    return await responses.respond_json(context, request, document)


async def _autocomplete(context: RepositoryContext, request: Request) -> Response:
    arguments = request.query_params
    if "id" in arguments:
        prerelease = arguments.get("prerelease", "").lower() == "true"
        shown = await feeds.completed_versions(context, request, arguments["id"], prerelease)
        return await responses.respond_json(
            context, request, documents.autocomplete(shown, len(shown))
        )
    ids, total = await feeds.completed_ids(context, request, arguments)
    return await responses.respond_json(context, request, documents.autocomplete(ids, total))


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """Answer a request to a NuGet group. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        # The generic engine says what a group takes.
        return await group.handle_group(context, request, path, serve)
    base = await responses.base(context, request)
    parsed = paths.classify(path)
    if parsed.kind == "v2":
        return await grouped_v2.answer(context, request, path, base)
    if path == paths.SERVICE_INDEX:
        audit = await feeds.vulnerability_index(context, request, base)
        index = documents.service_index(base, publish=False, vulnerabilities=audit is not None)
        return await responses.respond_json(context, request, index)
    if parsed.kind == "versions":
        listed = await feeds.versions_of(context, request, parsed.id)
        if not listed:
            raise _not_found()
        return await responses.respond_json(context, request, documents.version_list(listed))
    if parsed.kind in ("registration", "page", "leaf"):
        return await _registration(context, request, parsed, base)
    if parsed.kind == "search":
        found, total = await feeds.search(context, request, request.query_params, base)
        return await responses.respond_json(context, request, {"totalHits": total, "data": found})
    if parsed.kind == "autocomplete":
        return await _autocomplete(context, request)
    if path == paths.VULNERABILITY_INDEX:
        audit = await feeds.vulnerability_index(context, request, base)
        if audit is None:
            raise _not_found()
        return await responses.respond_json(context, request, audit)
    # A package, its `.nuspec`, a file of NuGet Audit's, a package at V2's address: the
    # first member that has it. Nothing else is asked of the members: what they would
    # answer has their addresses.
    if parsed.kind == "download" or path.startswith(paths.PACKAGES):
        return await group.handle_group(context, request, path, serve)
    if proxied.vulnerability_name(path) is not None:
        return await group.handle_group(context, request, path, serve)
    raise _not_found()
