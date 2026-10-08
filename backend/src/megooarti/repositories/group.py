"""Group repositories: several repositories behind one URL.

Members are tried in order and the first that has the path answers. Permission is
decided on the group, by the route, before this runs: members are not checked again.
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.formats import Serve
from megooarti.repositories.paths import normalise_path

# What a member may answer to mean "not from me; try the next": it lacks the path,
# its remote is unavailable, or it has no engine in this version.
TRY_NEXT = frozenset({404, 502, 503})
_SEEN = "megooarti.groups_seen"


async def member_contexts(context: RepositoryContext, request: Request) -> list[RepositoryContext]:
    """The online members of a group, in order, each as its own context.

    A group gives its members once in a request; asked again, it gives none. Cycles
    are refused when a group is saved, but two simultaneous saves could create one, and
    this makes that harmless.
    """
    seen = request.scope.setdefault(_SEEN, set())
    if context.repository.id in seen:
        return []
    seen.add(context.repository.id)
    return [
        await build_context(
            context.db, context.settings, member, context.principal, outbound=context.outbound
        )
        for member in await service.members(context.db, context.repository)
        if member.online
    ]


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """Answer a request to a group. `serve` is the dispatcher, used for each member."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A group repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    for member_context in await member_contexts(context, request):
        try:
            return await serve(member_context, request, path)
        except ApiError as error:
            if error.status_code not in TRY_NEXT:
                raise
    raise ApiError(404, "not_found", "No such file.")
