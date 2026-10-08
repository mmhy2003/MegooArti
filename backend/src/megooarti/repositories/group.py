"""Group repositories: several repositories behind one URL.

Members are tried in order and the first that has the path answers. Permission is
decided on the group, by the route, before this runs: members are not checked again.
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.paths import normalise_path

# What a member may answer to mean "not from me; try the next": it lacks the path,
# its remote is unavailable, or it has no engine in this version.
_TRY_NEXT = frozenset({404, 502, 503})
_SEEN = "megooarti.groups_seen"


async def handle_group(context: RepositoryContext, request: Request, path: str, serve) -> Response:
    """Answer a request to a group. `serve` is the dispatcher, used for each member."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A group repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    # Cycles are refused when a group is saved, but two simultaneous saves could create
    # one. Visiting each group once per request makes that harmless.
    seen = request.scope.setdefault(_SEEN, set())
    if context.repository.id not in seen:
        seen.add(context.repository.id)
        for member in await service.members(context.db, context.repository):
            if not member.online:
                continue
            member_context = await build_context(
                context.db, context.settings, member, context.principal
            )
            try:
                return await serve(member_context, request, path)
            except ApiError as error:
                if error.status_code not in _TRY_NEXT:
                    raise
    raise ApiError(404, "not_found", "No such file.")
