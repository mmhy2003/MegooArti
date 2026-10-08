"""Group repositories: several repositories behind one URL.

Members are tried in order and the first that has the path answers. Permission is
decided on the group, by the route, before this runs: members are not checked again.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.formats import Serve
from megooarti.repositories.models import Repository
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


@dataclass(frozen=True)
class Leaf:
    """A repository behind a group that is not itself a group."""

    context: RepositoryContext
    online: bool  # False if it is offline, or is reached only through an offline group


async def leaves(context: RepositoryContext) -> list[Leaf]:
    """Every hosted and proxy repository behind a group, in the order they are tried.

    For a format that answers from all of them at once instead of from the first that
    has the path. Offline ones are included and marked, because what an offline
    repository holds can still decide what the others may answer. A repository reached
    more than once is listed once, where it is first reached online if it ever is.
    """
    reached: list[tuple[Repository, bool]] = []
    walked = {context.repository.id: True}

    async def walk(repository: Repository, online: bool) -> None:
        for member in await service.members(context.db, repository):
            usable = online and member.online
            if member.type != "group":
                reached.append((member, usable))
            elif member.id not in walked or (usable and not walked[member.id]):
                # Again only if it was reached through something offline before, so a
                # cycle that slipped into the data ends.
                walked[member.id] = usable
                await walk(member, usable)

    await walk(context.repository, True)
    online = {member.id for member, usable in reached if usable}
    found: dict[uuid.UUID, Leaf] = {}
    for member, usable in reached:
        if member.id in found or (not usable and member.id in online):
            continue
        made = await build_context(
            context.db, context.settings, member, context.principal, outbound=context.outbound
        )
        found[member.id] = Leaf(made, usable)
    return list(found.values())


async def owners(
    found: Sequence[Leaf], namespace: str, name: str
) -> tuple[list[RepositoryContext], bool]:
    """The hosted repositories behind a group that hold a package.

    Returns those that are online, in order, and whether one that is offline holds it
    too. A package that a hosted repository holds is answered for by hosted
    repositories only: package names are not verified, so a public package of the
    same name must not add to it, nor stand in for it while its repository is offline.
    """
    online, offline = [], False
    for leaf in found:
        member = leaf.context
        if member.repository.type != "hosted" or not await member.names(namespace, [name]):
            continue
        if leaf.online:
            online.append(member)
        else:
            offline = True
    return online, offline


def proxies(found: Sequence[Leaf]) -> list[RepositoryContext]:
    """The online proxy repositories behind a group, in order."""
    return [
        leaf.context for leaf in found if leaf.online and leaf.context.repository.type == "proxy"
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
